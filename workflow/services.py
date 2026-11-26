"""
محرك الإحالات والمهام:
- إنشاء إحالات مباشرة، متتابعة، متوازية، أو للعلم فقط.
- حماية ضد الإرسال المكرر باستخدام idempotency_key.
- عزل التنبيهات عن معاملة حفظ الإحالة.
- تقييم شروط استكمال الإحالات المتوازية والمتتابعة.
"""
import logging
import math
from datetime import timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from accounts.services import PermissionService
from audit.services import AuditService
from notifications.models import Notification
from notifications.services import NotificationService
from subjects.models import Subject, SubjectAccessGrant
from subjects.services import ALLOWED_TRANSITIONS, transition_subject
from .models import (
    Referral,
    ReferralRecipient,
    Task,
    WorkflowStepDefinition,
    WorkflowTemplateVersion,
)

logger = logging.getLogger(__name__)


def _resolve_step_sla_hours(subject: Subject, target_users: list, target_units: list, template_step=None):
    """تحديد عدد ساعات المهلة (SLA) من خطوة القالب أو خطوات الإصدار المرتبط بالموضوع."""
    if template_step is not None and getattr(template_step, "sla_hours", None):
        return template_step.sla_hours
    if not getattr(subject, "workflow_template_version_id", None):
        return None
    steps = list(
        WorkflowStepDefinition.objects.filter(
            template_version_id=subject.workflow_template_version_id,
            sla_hours__isnull=False,
        ).order_by("step_order")
    )
    if not steps:
        return None
    unit_ids = {unit.id for unit in target_units if unit is not None}
    for usr in target_users:
        if getattr(usr, "current_unit", None):
            unit_ids.add(usr.current_unit.id)
    for step in steps:
        if step.suggested_unit_id and step.suggested_unit_id in unit_ids:
            return step.sla_hours
    return steps[0].sla_hours


def _compute_due_date_from_sla(sla_hours=None, subject: Subject | None = None):
    """تحويل ساعات SLA (أو أيام أولوية الموضوع) إلى تاريخ استحقاق تلقائي."""
    if sla_hours:
        days = max(1, math.ceil(sla_hours / 24))
        return timezone.localdate() + timedelta(days=days)
    if subject is not None and getattr(subject, "priority_id", None):
        sla_days = getattr(subject.priority, "sla_days", None)
        if sla_days:
            return timezone.localdate() + timedelta(days=sla_days)
    return None


class WorkflowEngineService:
    @classmethod
    def create_referral(
        cls,
        *,
        subject: Subject,
        referred_by,
        routing_mode: str,
        purpose: str,
        notes: str = "",
        target_users: list | None = None,
        target_units: list | None = None,
        parallel_completion_rule: str = Referral.ParallelCompletionRule.ALL,
        required_unit=None,
        due_date=None,
        idempotency_key: str | None = None,
        grant_explicit_access_for_secret: bool = True,
        enforce_hierarchy: bool = True,
        coordinator=None,
        template_step: WorkflowStepDefinition | None = None,
    ) -> Referral:
        target_users = target_users or []
        target_units = target_units or []
        if not target_users and not target_units:
            raise ValidationError("يجب تحديد مستخدم واحد أو وحدة تنظيمية واحدة على الأقل للإحالة.")
        if due_date == "":
            due_date = None

        if enforce_hierarchy and not getattr(referred_by, "is_superuser", False):
            if not PermissionService.can_act_on_subject(referred_by, subject):
                raise ValidationError("هذا الموضوع متاح للاطلاع فقط حالياً؛ لا يمكنك التعديل أو الإحالة حتى يردك في عهدتك التنفيذية.")
            if target_users:
                allowed_ids = set(
                    PermissionService.get_allowed_referral_targets(referred_by, subject).values_list("id", flat=True)
                )
                disallowed = [u for u in target_users if u.id not in allowed_ids]
                if disallowed:
                    raise ValidationError(
                        "التوجيه غير مسموح حسب التسلسل الهرمي أو عزل القطاعات: يوجّه المدير العام (أو سكرتاريته) إلى مشرف/رئيس القسم المختص فقط، ويوزّع مشرف/سكرتارية القسم على الموظف المختص التابع فقط."
                    )
            if target_units:
                allowed_unit_ids = set(
                    PermissionService.get_allowed_referral_units(referred_by, subject).values_list("id", flat=True)
                )
                disallowed_units = [unit for unit in target_units if unit.id not in allowed_unit_ids]
                if disallowed_units:
                    raise ValidationError(
                        "الوحدة التنظيمية المختارة خارج نطاق صلاحية الإحالة أو معزولة في قطاع/وحدة أخرى."
                    )
            if required_unit is not None:
                allowed_unit_ids = set(
                    PermissionService.get_allowed_referral_units(referred_by, subject).values_list("id", flat=True)
                )
                if required_unit.id not in allowed_unit_ids:
                    raise ValidationError("الجهة المطلوب ردها خارج نطاق الوحدات المصرح بإحالتها.")

        if idempotency_key:
            existing = Referral.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing

        delegation = PermissionService.get_acting_delegation(referred_by, "REFERRAL_CREATE", subject=subject)
        effective_coordinator = (
            coordinator
            if coordinator is not None
            else (referred_by if routing_mode == Referral.RoutingMode.PARALLEL else None)
        )
        if due_date is None:
            sla_hours = _resolve_step_sla_hours(subject, target_users, target_units, template_step=template_step)
            due_date = _compute_due_date_from_sla(sla_hours=sla_hours, subject=subject)

        try:
            with transaction.atomic():
                referral = Referral.objects.create(
                    subject=subject,
                    referred_by=referred_by,
                    acting_on_behalf_of=delegation.delegator if delegation else None,
                    coordinator=effective_coordinator,
                    routing_mode=routing_mode,
                    purpose=purpose,
                    parallel_completion_rule=parallel_completion_rule,
                    required_unit_for_completion=required_unit,
                    confidentiality=subject.confidentiality,
                    priority=subject.priority,
                    notes=notes,
                    due_date=due_date,
                    idempotency_key=idempotency_key or None,
                )

                targets = []
                for u in target_users:
                    targets.append(("user", u))
                for unit in target_units:
                    targets.append(("unit", unit))

                for idx, (kind, obj) in enumerate(targets, start=1):
                    is_active = True if routing_mode != Referral.RoutingMode.SEQUENTIAL else (idx == 1)
                    status = (
                        ReferralRecipient.RecipientStatus.PENDING
                        if is_active
                        else ReferralRecipient.RecipientStatus.WAITING_TURN
                    )
                    ReferralRecipient.objects.create(
                        referral=referral,
                        sequence_order=idx,
                        target_user=obj if kind == "user" else None,
                        target_unit=obj if kind == "unit" else (obj.current_unit if kind == "user" else None),
                        is_active_step=is_active,
                        status=status,
                    )
                    if kind == "user" and grant_explicit_access_for_secret and subject.confidentiality.overrides_hierarchy:
                        SubjectAccessGrant.objects.get_or_create(
                            subject=subject,
                            user=obj,
                            defaults={
                                "access_type": SubjectAccessGrant.AccessType.GRANT,
                                "granted_by": referred_by,
                                "reason": "تصريح تلقائي عبر إحالة مباشرة لمعاملة سرية",
                            },
                        )

                # "للعلم فقط" لا يغيّر المالك التنفيذي ولا ينتج عنه تكليف
                if purpose != Referral.Purpose.FOR_INFO:
                    owner_changed = False
                    if routing_mode == Referral.RoutingMode.PARALLEL:
                        # في الإحالة المتوازية يحتفظ المنسق (أو المحيل افتراضياً) بالملكية التنفيذية أثناء التوازي
                        subject.current_owner = effective_coordinator or referred_by
                        owner_changed = True
                    elif target_users:
                        subject.current_owner = target_users[0]
                        owner_changed = True

                    if subject.status in (
                        Subject.Status.NEW,
                        Subject.Status.INCOMING,
                        Subject.Status.UNDER_REVIEW,
                        Subject.Status.REOPENED,
                    ):
                        if owner_changed:
                            subject.save(update_fields=["current_owner"])
                        transition_subject(
                            subject,
                            Subject.Status.IN_PROGRESS,
                            referred_by,
                            reason="تفعيل الموضوع عند إنشاء إحالة",
                        )
                    elif owner_changed:
                        subject.last_action_at = timezone.now()
                        subject.version_lock += 1
                        subject.save(update_fields=["current_owner", "last_action_at", "version_lock"])

                AuditService.record_activity(
                    subject=subject,
                    action_type="REFERRAL_FOR_INFO" if purpose == Referral.Purpose.FOR_INFO else "REFERRAL_CREATED",
                    actor_user=referred_by,
                    acting_on_behalf_of=delegation.delegator if delegation else None,
                    delegation=delegation,
                    description=(
                        f"{'إحالة للعلم/للاطلاع' if purpose == Referral.Purpose.FOR_INFO else 'إحالة'} "
                        f"({referral.get_routing_mode_display()}) — {notes or 'دون ملاحظات إضافية'}"
                    ),
                )

                # إرسال الإشعارات بعد نجاح تثبيت المعاملة داخل try/except كي لا يتأثر الحفظ
                active_recipients = [
                    rec.target_user
                    for rec in referral.recipients.filter(is_active_step=True).select_related("target_user")
                    if rec.target_user is not None
                ]
                prio_code = getattr(subject.priority, "code", "NORMAL") if subject.priority_id else "NORMAL"
                ref_id = referral.id
                subj_id = subject.id
                subj_num = subject.internal_number
                subj_title = subject.title
                purpose_disp = referral.get_purpose_display()

                def _notify_referral_recipients():
                    for target_user in active_recipients:
                        try:
                            NotificationService.notify(
                                recipient=target_user,
                                subject=subject,
                                category=Notification.Category.INCOMING_REFERRAL,
                                priority=prio_code,
                                title=f"إحالة جديدة على الموضوع {subj_num}",
                                message=f"وردتك إحالة ({purpose_disp}): {subj_title}",
                                link_url=f"/subjects/{subj_id}/",
                            )
                        except Exception:
                            logger.exception("تعذر إرسال إشعار الإحالة %s للمستخدم %s", ref_id, target_user.id)

                transaction.on_commit(_notify_referral_recipients)
        except IntegrityError:
            if idempotency_key:
                existing = Referral.objects.filter(idempotency_key=idempotency_key).first()
                if existing:
                    return existing
            raise

        return referral

    @classmethod
    @transaction.atomic
    def acknowledge_or_complete_recipient(
        cls,
        *,
        recipient_item: ReferralRecipient,
        user,
        response_notes: str = "",
        complete: bool = True,
        force_complete_parallel: bool = False,
    ) -> Referral:
        # قفل الإحالة ثم جميع مستلميها بترتيب ثابت لمنع التعارض المتزامن والـ Deadlock
        referral = (
            Referral.objects.select_for_update()
            .select_related("subject", "referred_by")
            .get(id=recipient_item.referral_id)
        )
        locked_recipients = list(
            referral.recipients.select_for_update().order_by("sequence_order", "id")
        )
        locked_item = next((item for item in locked_recipients if item.id == recipient_item.id), None)
        if locked_item is None:
            raise ValidationError("عنصر المستلم غير مرتبط بهذه الإحالة.")
        recipient_item = locked_item
        now = timezone.now()

        if referral.purpose == Referral.Purpose.FOR_INFO:
            recipient_item.status = ReferralRecipient.RecipientStatus.VIEWED_ONLY
            recipient_item.received_at = recipient_item.received_at or now
            recipient_item.received_by = recipient_item.received_by or user
            recipient_item.responded_at = now
            recipient_item.response_notes = response_notes or "تم الاطلاع للعلم"
            recipient_item.save()
            AuditService.record_activity(
                subject=referral.subject,
                action_type="VIEWED_FOR_INFO",
                actor_user=user,
                description=f"تم الاطلاع للعلم دون تكليف بواسطة {user}",
            )
            return referral

        if referral.is_completed:
            raise ValidationError("تم استكمال هذه الإحالة مسبقاً.")
        if recipient_item.status in (
            ReferralRecipient.RecipientStatus.RESPONDED,
            ReferralRecipient.RecipientStatus.SKIPPED_NO_RESPONSE,
        ):
            raise ValidationError("تم تسجيل الرد أو تجاوز هذا الطرف مسبقاً.")

        if not complete:
            recipient_item.status = ReferralRecipient.RecipientStatus.RECEIVED
            recipient_item.received_at = recipient_item.received_at or now
            recipient_item.received_by = user
            recipient_item.save(update_fields=["status", "received_at", "received_by"])
            AuditService.record_activity(
                subject=referral.subject,
                action_type="REFERRAL_RECEIVED",
                actor_user=user,
                description=f"تم استلام الإحالة فعلياً بواسطة {user}",
            )
            return referral

        recipient_item.status = ReferralRecipient.RecipientStatus.RESPONDED
        recipient_item.received_at = recipient_item.received_at or now
        recipient_item.received_by = recipient_item.received_by or user
        recipient_item.responded_at = now
        recipient_item.response_notes = response_notes
        recipient_item.is_active_step = False
        recipient_item.save()

        # تفعيل الخطوة التالية في الإحالة المتتابعة
        if referral.routing_mode == Referral.RoutingMode.SEQUENTIAL:
            next_item = next(
                (item for item in locked_recipients if item.sequence_order > recipient_item.sequence_order),
                None,
            )
            if next_item:
                next_item.is_active_step = True
                next_item.status = ReferralRecipient.RecipientStatus.PENDING
                next_item.save(update_fields=["is_active_step", "status"])
                if next_item.target_user:
                    referral.subject.current_owner = next_item.target_user
                    referral.subject.save(update_fields=["current_owner"])
            else:
                referral.is_completed = True
                referral.completed_at = now
                referral.save(update_fields=["is_completed", "completed_at"])

        # تقييم شروط استكمال الإحالة المتوازية
        elif referral.routing_mode == Referral.RoutingMode.PARALLEL:
            all_items = locked_recipients
            rule = referral.parallel_completion_rule
            done = False
            if rule == Referral.ParallelCompletionRule.FIRST_RESPONSE:
                done = True
            elif rule == Referral.ParallelCompletionRule.SPECIFIC_UNIT and referral.required_unit_for_completion_id:
                done = any(
                    item.target_unit_id == referral.required_unit_for_completion_id
                    and item.status == ReferralRecipient.RecipientStatus.RESPONDED
                    for item in all_items
                )
            elif rule == Referral.ParallelCompletionRule.ALLOW_WITH_MISSING and force_complete_parallel:
                done = True
            else:
                done = all(item.status == ReferralRecipient.RecipientStatus.RESPONDED for item in all_items)

            if done:
                # إلغاء بقية المستلمين الذين لم يردّوا عند تحقق شرط اكتمال التوازي
                for item in all_items:
                    if item.status != ReferralRecipient.RecipientStatus.RESPONDED:
                        item.status = ReferralRecipient.RecipientStatus.SKIPPED_NO_RESPONSE
                        item.is_active_step = False
                        item.save(update_fields=["status", "is_active_step"])
                referral.is_completed = True
                referral.completed_at = now
                referral.save(update_fields=["is_completed", "completed_at"])
        else:
            referral.is_completed = True
            referral.completed_at = now
            referral.save(update_fields=["is_completed", "completed_at"])

        AuditService.record_activity(
            subject=referral.subject,
            action_type="REFERRAL_RESPONDED",
            actor_user=user,
            description=f"إفادة على الإحالة بواسطة {user}: {response_notes or 'تم التنفيذ'}",
        )
        if referral.referred_by and referral.referred_by_id != user.id:
            ref_by = referral.referred_by
            subj = referral.subject
            prio_code = getattr(subj.priority, "code", "NORMAL") if subj.priority_id else "NORMAL"
            ref_id = referral.id
            msg_notes = response_notes or "تم التنفيذ"

            def _notify_referrer():
                try:
                    NotificationService.notify(
                        recipient=ref_by,
                        subject=subj,
                        category=Notification.Category.REPLY_MEMO,
                        priority=prio_code,
                        title=f"تمت الإفادة على الإحالة ({subj.internal_number})",
                        message=f"أفاد {user} على الموضوع «{subj.title}»: {msg_notes}",
                        link_url=f"/subjects/{subj.id}/",
                    )
                except Exception:
                    logger.exception("تعذر إرسال إشعار الإفادة للإحالة %s", ref_id)

            transaction.on_commit(_notify_referrer)
        return referral

    @staticmethod
    @transaction.atomic
    def create_task(
        *,
        subject: Subject,
        title: str,
        assigned_to,
        assigned_by,
        description: str = "",
        due_date=None,
        priority=None,
        referral=None,
    ) -> Task:
        task = Task.objects.create(
            subject=subject,
            referral=referral,
            title=title,
            description=description,
            assigned_to=assigned_to,
            assigned_unit=assigned_to.current_unit,
            assigned_by=assigned_by,
            priority=priority or subject.priority,
            due_date=due_date,
        )
        if subject.confidentiality.overrides_hierarchy:
            SubjectAccessGrant.objects.get_or_create(
                subject=subject,
                user=assigned_to,
                defaults={
                    "access_type": SubjectAccessGrant.AccessType.GRANT,
                    "granted_by": assigned_by,
                    "reason": "تصريح تلقائي عبر تكليف بمهمة على موضوع سري",
                },
            )
        AuditService.record_activity(
            subject=subject,
            action_type="TASK_CREATED",
            actor_user=assigned_by,
            description=f"تكليف بمهمة ({task.title}) إلى {assigned_to}",
        )
        prio_code = getattr(task.priority, "code", "NORMAL") if task.priority_id else "NORMAL"
        task_id = task.id
        task_title = task.title
        subj_id = subject.id
        subj_num = subject.internal_number

        def _notify_task_assignee():
            try:
                NotificationService.notify(
                    recipient=assigned_to,
                    subject=subject,
                    category=Notification.Category.DECISION_TASK,
                    priority=prio_code,
                    title=f"مهمة جديدة: {task_title}",
                    message=f"تم تكليفك بمهمة على الموضوع {subj_num}",
                    link_url=f"/subjects/{subj_id}/",
                )
            except Exception:
                logger.exception("تعذر إرسال إشعار المهمة %s", task_id)

        transaction.on_commit(_notify_task_assignee)
        return task

    @classmethod
    @transaction.atomic
    def apply_template(
        cls,
        subject: Subject,
        template_version: WorkflowTemplateVersion,
        user,
    ) -> list[Referral]:
        """تطبيق إصدار قالب مسار العمل على الموضوع بإنشاء الإحالات وفق WorkflowStepDefinition."""
        if subject.status == Subject.Status.CLOSED:
            raise ValidationError("لا يمكن تطبيق قالب مسار عمل على موضوع مغلق.")
        if template_version is None:
            raise ValidationError("يرجى اختيار إصدار قالب مسار عمل صالح.")

        steps = list(
            template_version.steps.select_related(
                "suggested_unit__manager_employee__user_account"
            ).order_by("step_order", "id")
        )
        if not steps:
            raise ValidationError("إصدار القالب المختار لا يحتوي على خطوات معرفة.")

        subject.workflow_template_version = template_version
        subject.save(update_fields=["workflow_template_version"])

        created_referrals: list[Referral] = []
        for step in steps:
            target_unit = step.suggested_unit or subject.org_unit
            note_parts = [f"خطوة القالب ({step.step_order}): {step.step_title}"]
            if step.suggested_action:
                note_parts.append(step.suggested_action)
            step_due_date = _compute_due_date_from_sla(sla_hours=step.sla_hours, subject=subject)
            ref = cls.create_referral(
                subject=subject,
                referred_by=user,
                routing_mode=Referral.RoutingMode.DIRECT,
                purpose=Referral.Purpose.FOR_EXECUTION,
                notes=" — ".join(note_parts),
                target_units=[target_unit],
                due_date=step_due_date,
                enforce_hierarchy=False,
                template_step=step,
            )
            created_referrals.append(ref)

        AuditService.record_activity(
            subject=subject,
            action_type="WORKFLOW_TEMPLATE_APPLIED",
            actor_user=user,
            description=f"تطبيق قالب مسار العمل ({template_version}) بعدد {len(created_referrals)} إحالة.",
        )
        return created_referrals

    @classmethod
    @transaction.atomic
    def reject_or_return_recipient(
        cls,
        *,
        recipient_item: ReferralRecipient,
        user,
        reason: str,
    ) -> Referral:
        """رفض أو إرجاع الإحالة من المستلم إلى المحيل مع سبب إجباري وإعادة العهدة للمحيل."""
        clean_reason = (reason or "").strip()
        if not clean_reason:
            raise ValidationError("يجب كتابة سبب الرفض أو الإرجاع.")

        referral = (
            Referral.objects.select_for_update()
            .select_related("subject", "referred_by")
            .get(id=recipient_item.referral_id)
        )
        locked_recipients = list(
            referral.recipients.select_for_update().order_by("sequence_order", "id")
        )
        locked_item = next((item for item in locked_recipients if item.id == recipient_item.id), None)
        if locked_item is None:
            raise ValidationError("عنصر المستلم غير مرتبط بهذه الإحالة.")

        if referral.purpose == Referral.Purpose.FOR_INFO:
            raise ValidationError("الإحالة للعلم والاطلاع فقط لا تقبل الرفض أو الإرجاع.")
        if referral.is_completed or referral.is_withdrawn:
            raise ValidationError("لا يمكن رفض أو إرجاع إحالة مكتملة أو مسحوبة.")
        if not locked_item.is_active_step or locked_item.status not in (
            ReferralRecipient.RecipientStatus.PENDING,
            ReferralRecipient.RecipientStatus.RECEIVED,
        ):
            raise ValidationError("هذا الطرف غير نشط أو تم التعامل معه مسبقاً.")

        now = timezone.now()
        locked_item.status = ReferralRecipient.RecipientStatus.RETURNED
        locked_item.is_active_step = False
        locked_item.received_at = locked_item.received_at or now
        locked_item.received_by = locked_item.received_by or user
        locked_item.responded_at = now
        locked_item.response_notes = clean_reason
        locked_item.save()

        for other in locked_recipients:
            if other.id != locked_item.id and (
                other.is_active_step
                or other.status in (
                    ReferralRecipient.RecipientStatus.PENDING,
                    ReferralRecipient.RecipientStatus.WAITING_TURN,
                )
            ):
                other.is_active_step = False
                if other.status in (
                    ReferralRecipient.RecipientStatus.PENDING,
                    ReferralRecipient.RecipientStatus.WAITING_TURN,
                ):
                    other.status = ReferralRecipient.RecipientStatus.SKIPPED_NO_RESPONSE
                other.save(update_fields=["status", "is_active_step"])

        referral.is_completed = True
        referral.completed_at = now
        referral.save(update_fields=["is_completed", "completed_at"])

        locked_subject = Subject.objects.select_for_update().get(id=referral.subject_id)
        locked_subject.current_owner = referral.referred_by
        locked_subject.save(update_fields=["current_owner"])
        referral.subject.current_owner = referral.referred_by

        if (
            locked_subject.status != Subject.Status.UNDER_REVIEW
            and Subject.Status.UNDER_REVIEW in ALLOWED_TRANSITIONS.get(locked_subject.status, set())
        ):
            transition_subject(
                referral.subject,
                Subject.Status.UNDER_REVIEW,
                user,
                reason=f"إرجاع الإحالة إلى المحيل: {clean_reason}",
            )
        else:
            locked_subject.version_lock += 1
            locked_subject.last_action_at = now
            locked_subject.save(update_fields=["version_lock", "last_action_at"])

        AuditService.record_activity(
            subject=referral.subject,
            action_type="REFERRAL_RETURNED",
            actor_user=user,
            description=f"رفض/إرجاع الإحالة إلى {referral.referred_by} — السبب: {clean_reason}",
        )

        if referral.referred_by and referral.referred_by_id != user.id:
            ref_by = referral.referred_by
            subj = referral.subject
            prio_code = getattr(subj.priority, "code", "NORMAL") if subj.priority_id else "NORMAL"
            ref_id = referral.id

            def _notify_returned():
                try:
                    NotificationService.notify(
                        recipient=ref_by,
                        subject=subj,
                        category=Notification.Category.REPLY_MEMO,
                        priority=prio_code,
                        title=f"تم إرجاع الإحالة على الموضوع {subj.internal_number}",
                        message=f"أرجع {user} الإحالة إليك للسبب: {clean_reason}",
                        link_url=f"/subjects/{subj.id}/",
                    )
                except Exception:
                    logger.exception("تعذر إرسال إشعار إرجاع الإحالة %s", ref_id)

            transaction.on_commit(_notify_returned)

        return referral

    @classmethod
    @transaction.atomic
    def withdraw_referral(
        cls,
        *,
        referral: Referral,
        user,
        reason: str = "",
    ) -> Referral:
        """سحب الإحالة من المحيل طالما لم يتم استلامها أو الرد عليها من أي مستلم."""
        locked_ref = (
            Referral.objects.select_for_update()
            .select_related("subject", "referred_by")
            .get(id=referral.id)
        )
        locked_recipients = list(
            locked_ref.recipients.select_for_update().select_related("target_user").order_by("sequence_order", "id")
        )

        delegation = PermissionService.get_acting_delegation(user, "REFERRAL_CREATE", subject=locked_ref.subject)
        is_authorized = (
            getattr(user, "is_superuser", False)
            or locked_ref.referred_by_id == user.id
            or (delegation is not None and delegation.delegator_id == locked_ref.referred_by_id)
        )
        if not is_authorized:
            raise PermissionDenied("سحب الإحالة متاح للمحيل أو المفوض عنه فقط.")

        if locked_ref.is_withdrawn or locked_ref.is_completed:
            raise ValidationError("لا يمكن سحب إحالة مكتملة أو مسحوبة مسبقاً.")

        already_received = any(
            rec.received_at is not None
            or rec.status in (
                ReferralRecipient.RecipientStatus.RECEIVED,
                ReferralRecipient.RecipientStatus.RESPONDED,
                ReferralRecipient.RecipientStatus.VIEWED_ONLY,
                ReferralRecipient.RecipientStatus.RETURNED,
            )
            for rec in locked_recipients
        )
        if already_received:
            raise ValidationError("تعذر سحب الإحالة لأنها استُلمت بالفعل من أحد المحال إليهم.")

        now = timezone.now()
        notified_users = []
        for rec in locked_recipients:
            if rec.target_user and rec.target_user_id != user.id:
                notified_users.append(rec.target_user)
            rec.status = ReferralRecipient.RecipientStatus.WITHDRAWN
            rec.is_active_step = False
            rec.save(update_fields=["status", "is_active_step"])

        locked_ref.is_withdrawn = True
        locked_ref.is_completed = True
        locked_ref.completed_at = now
        locked_ref.save(update_fields=["is_withdrawn", "is_completed", "completed_at"])

        clean_reason = (reason or "").strip()
        if locked_ref.purpose != Referral.Purpose.FOR_INFO:
            locked_subject = Subject.objects.select_for_update().get(id=locked_ref.subject_id)
            locked_subject.current_owner = locked_ref.referred_by
            locked_subject.save(update_fields=["current_owner"])
            locked_ref.subject.current_owner = locked_ref.referred_by

            has_other_open = (
                Referral.objects.filter(
                    subject_id=locked_subject.id,
                    is_completed=False,
                    is_withdrawn=False,
                )
                .exclude(purpose=Referral.Purpose.FOR_INFO)
                .exclude(id=locked_ref.id)
                .exists()
            )
            if (
                not has_other_open
                and locked_subject.status == Subject.Status.IN_PROGRESS
                and Subject.Status.UNDER_REVIEW in ALLOWED_TRANSITIONS.get(locked_subject.status, set())
            ):
                transition_subject(
                    locked_ref.subject,
                    Subject.Status.UNDER_REVIEW,
                    user,
                    reason=clean_reason or "سحب الإحالة من المحيل قبل الاستلام",
                )
            else:
                locked_subject.version_lock += 1
                locked_subject.last_action_at = now
                locked_subject.save(update_fields=["version_lock", "last_action_at"])

        AuditService.record_activity(
            subject=locked_ref.subject,
            action_type="REFERRAL_WITHDRAWN",
            actor_user=user,
            acting_on_behalf_of=delegation.delegator if delegation else None,
            delegation=delegation,
            description=f"تم سحب الإحالة رقم {locked_ref.id} بواسطة {user}" + (f" — {clean_reason}" if clean_reason else ""),
        )

        if notified_users:
            subj = locked_ref.subject
            prio_code = getattr(subj.priority, "code", "NORMAL") if subj.priority_id else "NORMAL"
            ref_id = locked_ref.id

            def _notify_withdrawn():
                for target_user in notified_users:
                    try:
                        NotificationService.notify(
                            recipient=target_user,
                            subject=subj,
                            category=Notification.Category.SYSTEM,
                            priority=prio_code,
                            title=f"تم سحب الإحالة على الموضوع {subj.internal_number}",
                            message=f"قام {user} بسحب الإحالة قبل استلامها" + (f" ({clean_reason})" if clean_reason else "."),
                            link_url=f"/subjects/{subj.id}/",
                        )
                    except Exception:
                        logger.exception("تعذر إرسال إشعار سحب الإحالة %s للمستخدم %s", ref_id, target_user.id)

            transaction.on_commit(_notify_withdrawn)

        return locked_ref

    @classmethod
    @transaction.atomic
    def reassign_recipient(
        cls,
        *,
        recipient_item: ReferralRecipient,
        new_user,
        user,
        reason: str = "",
    ) -> ReferralRecipient:
        """إعادة إسناد مستلم معلق لمستخدم آخر مع تحديث العهدة وتسجيل النشاط والإشعار."""
        if new_user is None or not getattr(new_user, "is_active", False):
            raise ValidationError("يجب اختيار مستخدم نشط لإعادة الإسناد.")

        referral = (
            Referral.objects.select_for_update()
            .select_related("subject", "referred_by")
            .get(id=recipient_item.referral_id)
        )
        locked_recipients = list(
            referral.recipients.select_for_update().select_related("target_user", "target_unit").order_by("sequence_order", "id")
        )
        locked_item = next((item for item in locked_recipients if item.id == recipient_item.id), None)
        if locked_item is None:
            raise ValidationError("عنصر المستلم غير مرتبط بهذه الإحالة.")

        delegation = PermissionService.get_acting_delegation(user, "REFERRAL_CREATE", subject=referral.subject)
        is_authorized = (
            getattr(user, "is_superuser", False)
            or referral.referred_by_id == user.id
            or (delegation is not None and delegation.delegator_id == referral.referred_by_id)
            or PermissionService.can_act_on_subject(user, referral.subject)
        )
        if not is_authorized:
            raise PermissionDenied("ليس لديك صلاحية إعادة إسناد هذه الإحالة.")

        # افحص قائمة المستلمين المسموح بها داخل الخدمة نفسها؛ لا تعتمد على تحقق واجهة المستخدم.
        allowed_targets = PermissionService.get_allowed_referral_targets(user, referral.subject)
        if not allowed_targets.filter(id=new_user.id).exists():
            raise PermissionDenied("المستخدم المختار خارج نطاق المستلمين المسموح بهم لهذه الإحالة.")

        if referral.is_completed or referral.is_withdrawn:
            raise ValidationError("لا يمكن إعادة إسناد مستلم في إحالة مكتملة أو مسحوبة.")
        if locked_item.status not in (
            ReferralRecipient.RecipientStatus.PENDING,
            ReferralRecipient.RecipientStatus.WAITING_TURN,
        ):
            raise ValidationError("إعادة الإسناد متاحة للمستلم المعلّق فقط قبل الاستلام أو الرد.")
        if locked_item.target_user_id == new_user.id:
            raise ValidationError("المستخدم المختار هو نفسه المستلم الحالي.")

        old_user = locked_item.target_user
        old_label = str(old_user or locked_item.target_unit or "غير محدد")
        locked_item.target_user = new_user
        locked_item.target_unit = new_user.current_unit
        locked_item.save(update_fields=["target_user", "target_unit"])

        if referral.subject.confidentiality.overrides_hierarchy:
            SubjectAccessGrant.objects.get_or_create(
                subject=referral.subject,
                user=new_user,
                defaults={
                    "access_type": SubjectAccessGrant.AccessType.GRANT,
                    "granted_by": user,
                    "reason": "تصريح تلقائي عبر إعادة إسناد إحالة لمعاملة سرية",
                },
            )

        clean_reason = (reason or "").strip()
        locked_subject = Subject.objects.select_for_update().get(id=referral.subject_id)
        if referral.purpose != Referral.Purpose.FOR_INFO:
            if referral.routing_mode != Referral.RoutingMode.PARALLEL and locked_item.is_active_step:
                locked_subject.current_owner = new_user
                locked_subject.save(update_fields=["current_owner"])
                referral.subject.current_owner = new_user

            if locked_subject.status in (
                Subject.Status.NEW,
                Subject.Status.INCOMING,
                Subject.Status.UNDER_REVIEW,
                Subject.Status.REOPENED,
            ):
                transition_subject(
                    referral.subject,
                    Subject.Status.IN_PROGRESS,
                    user,
                    reason=clean_reason or f"إعادة إسناد الإحالة إلى {new_user}",
                )
            else:
                locked_subject.version_lock += 1
                locked_subject.last_action_at = timezone.now()
                locked_subject.save(update_fields=["version_lock", "last_action_at"])

        AuditService.record_activity(
            subject=referral.subject,
            action_type="REFERRAL_REASSIGNED",
            actor_user=user,
            acting_on_behalf_of=delegation.delegator if delegation else None,
            delegation=delegation,
            description=f"إعادة إسناد الإحالة من ({old_label}) إلى ({new_user})" + (f" — {clean_reason}" if clean_reason else ""),
        )

        subj = referral.subject
        prio_code = getattr(subj.priority, "code", "NORMAL") if subj.priority_id else "NORMAL"
        ref_id = referral.id

        def _notify_reassigned():
            if new_user.id != user.id:
                try:
                    NotificationService.notify(
                        recipient=new_user,
                        subject=subj,
                        category=Notification.Category.INCOMING_REFERRAL,
                        priority=prio_code,
                        title=f"تم إسناد إحالة إليك على الموضوع {subj.internal_number}",
                        message=f"أسند {user} إليك إحالة الموضوع «{subj.title}»" + (f" — {clean_reason}" if clean_reason else "."),
                        link_url=f"/subjects/{subj.id}/",
                    )
                except Exception:
                    logger.exception("تعذر إرسال إشعار إعادة الإسناد %s للمستخدم الجديد %s", ref_id, new_user.id)
            if old_user and old_user.id not in (user.id, new_user.id):
                try:
                    NotificationService.notify(
                        recipient=old_user,
                        subject=subj,
                        category=Notification.Category.SYSTEM,
                        priority=prio_code,
                        title=f"تمت إعادة إسناد الإحالة ({subj.internal_number})",
                        message=f"أُعيد إسناد الإحالة منك إلى {new_user} بواسطة {user}.",
                        link_url=f"/subjects/{subj.id}/",
                    )
                except Exception:
                    logger.exception("تعذر إرسال إشعار إعادة الإسناد %s للمستخدم السابق %s", ref_id, old_user.id)

        transaction.on_commit(_notify_reassigned)
        return locked_item


def apply_template(subject: Subject, template_version: WorkflowTemplateVersion, user) -> list[Referral]:
    """واجهة مختصرة لتطبيق إصدار قالب مسار عمل على الموضوع."""
    return WorkflowEngineService.apply_template(subject=subject, template_version=template_version, user=user)

