"""
خدمات الأعمال الأساسية للموضوعات:
- الإنشاء الذري بالترقيم الآمن
- اكتشاف تعارض التعديل المتزامن (Optimistic Locking)
- التعليق والاستيفاء والاستئناف
- الإغلاق الرسمي المشروط والإغلاق الاستثنائي وإعادة الفتح
"""
from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from accounts.services import PermissionService
from audit.services import AuditService
from core.models import SystemSequence
from .models import Subject, SubjectStatusHistory, SubjectSuspension


class OptimisticLockError(ValidationError):
    """يُطلق عند محاولة حفظ بيانات قديمة لنسخة موضوع تم تعديله من مستخدم آخر."""


# خريطة الانتقالات المسموحة بين حالات الموضوع لضمان سلامة دورة العمل
_S = Subject.Status
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    _S.NEW: {
        _S.INCOMING,
        _S.UNDER_REVIEW,
        _S.IN_PROGRESS,
        _S.AWAITING_APPROVAL,
        _S.AWAITING_COMMITTEE,
        _S.SUSPENDED,
        _S.DECISION_ISSUED,
        _S.DISTRIBUTING,
        _S.FINAL_EXECUTION,
        _S.COMPLETED,
        _S.CLOSED,
        _S.REJECTED,
        _S.CANCELLED,
    },
    _S.INCOMING: {
        _S.UNDER_REVIEW,
        _S.IN_PROGRESS,
        _S.AWAITING_APPROVAL,
        _S.AWAITING_COMMITTEE,
        _S.SUSPENDED,
        _S.DECISION_ISSUED,
        _S.DISTRIBUTING,
        _S.FINAL_EXECUTION,
        _S.COMPLETED,
        _S.CLOSED,
        _S.REJECTED,
        _S.CANCELLED,
    },
    _S.UNDER_REVIEW: {
        _S.IN_PROGRESS,
        _S.AWAITING_APPROVAL,
        _S.AWAITING_COMMITTEE,
        _S.SUSPENDED,
        _S.DECISION_ISSUED,
        _S.DISTRIBUTING,
        _S.FINAL_EXECUTION,
        _S.COMPLETED,
        _S.CLOSED,
        _S.REJECTED,
        _S.CANCELLED,
    },
    _S.IN_PROGRESS: {
        _S.UNDER_REVIEW,
        _S.AWAITING_APPROVAL,
        _S.AWAITING_COMMITTEE,
        _S.SUSPENDED,
        _S.DECISION_ISSUED,
        _S.DISTRIBUTING,
        _S.FINAL_EXECUTION,
        _S.COMPLETED,
        _S.CLOSED,
        _S.REJECTED,
        _S.CANCELLED,
    },
    _S.AWAITING_APPROVAL: {
        _S.UNDER_REVIEW,
        _S.IN_PROGRESS,
        _S.AWAITING_COMMITTEE,
        _S.SUSPENDED,
        _S.DECISION_ISSUED,
        _S.DISTRIBUTING,
        _S.FINAL_EXECUTION,
        _S.COMPLETED,
        _S.CLOSED,
        _S.REJECTED,
        _S.CANCELLED,
    },
    _S.AWAITING_COMMITTEE: {
        _S.UNDER_REVIEW,
        _S.IN_PROGRESS,
        _S.AWAITING_APPROVAL,
        _S.SUSPENDED,
        _S.DECISION_ISSUED,
        _S.DISTRIBUTING,
        _S.FINAL_EXECUTION,
        _S.COMPLETED,
        _S.CLOSED,
        _S.REJECTED,
        _S.CANCELLED,
    },
    _S.SUSPENDED: {
        _S.IN_PROGRESS,
        _S.UNDER_REVIEW,
        _S.AWAITING_APPROVAL,
        _S.AWAITING_COMMITTEE,
        _S.DECISION_ISSUED,
        _S.CANCELLED,
    },
    _S.DECISION_ISSUED: {
        _S.DISTRIBUTING,
        _S.FINAL_EXECUTION,
        _S.COMPLETED,
        _S.SUSPENDED,
        _S.CLOSED,
        _S.CANCELLED,
    },
    _S.DISTRIBUTING: {
        _S.FINAL_EXECUTION,
        _S.COMPLETED,
        _S.SUSPENDED,
        _S.CLOSED,
    },
    _S.FINAL_EXECUTION: {
        _S.COMPLETED,
        _S.SUSPENDED,
        _S.CLOSED,
    },
    _S.COMPLETED: {
        _S.CLOSED,
        _S.REOPENED,
    },
    _S.CLOSED: {
        _S.REOPENED,
    },
    _S.REOPENED: {
        _S.UNDER_REVIEW,
        _S.IN_PROGRESS,
        _S.AWAITING_APPROVAL,
        _S.AWAITING_COMMITTEE,
        _S.SUSPENDED,
        _S.DECISION_ISSUED,
        _S.DISTRIBUTING,
        _S.FINAL_EXECUTION,
        _S.COMPLETED,
        _S.CLOSED,
        _S.REJECTED,
        _S.CANCELLED,
    },
    _S.REJECTED: {
        _S.REOPENED,
    },
    _S.CANCELLED: set(),
}


@transaction.atomic
def transition_subject(subject: Subject, new_status: str, user, reason: str = "") -> Subject:
    """
    التحقق من انتقال حالة الموضوع وفق ALLOWED_TRANSITIONS،
    وزيادة version_lock، وتحديث سجل الحالات وسجل النشاط ActivityLog.
    """
    locked_subject = Subject.objects.select_for_update().get(id=subject.id)
    prev_status = locked_subject.status
    allowed = ALLOWED_TRANSITIONS.get(prev_status, set())
    if new_status not in allowed:
        target_label = Subject.Status(new_status).label if new_status in Subject.Status.values else new_status
        raise ValidationError(
            f"الانتقال من الحالة ({locked_subject.get_status_display()}) إلى ({target_label}) غير مسموح."
        )

    now = timezone.now()
    locked_subject.status = new_status
    locked_subject.version_lock += 1
    locked_subject.last_action_at = now
    locked_subject.save(update_fields=["status", "version_lock", "last_action_at"])

    # مزامنة الكائن الممرَّر في الذاكرة مع القيم المحفوظة
    subject.status = locked_subject.status
    subject.version_lock = locked_subject.version_lock
    subject.last_action_at = locked_subject.last_action_at

    SubjectStatusHistory.objects.create(
        subject=locked_subject,
        from_status=prev_status,
        to_status=new_status,
        changed_by=user,
        reason=reason or f"تغيير الحالة من {prev_status} إلى {new_status}",
    )
    AuditService.record_activity(
        subject=locked_subject,
        action_type="SUBJECT_STATUS_CHANGED",
        actor_user=user,
        description=(
            f"تغيير حالة الموضوع من ({prev_status}) إلى ({new_status})"
            + (f": {reason}" if reason else "")
        ),
    )
    return subject


class SubjectService:
    transition_subject = staticmethod(transition_subject)

    @staticmethod
    def get_current_stage_label(subject: Subject) -> str:
        """اسم المرحلة الحالية للعرض في نتائج البحث دون تعديل حالة الموضوع أو مساره."""
        if subject.status == Subject.Status.CLOSED:
            return "مغلق"
        if subject.status == Subject.Status.SUSPENDED:
            return "معلق لاستيفاء المطلوب"
        if subject.status in (
            Subject.Status.DECISION_ISSUED,
            Subject.Status.DISTRIBUTING,
            Subject.Status.FINAL_EXECUTION,
            Subject.Status.COMPLETED,
        ):
            return subject.get_status_display()

        for referral in subject.referrals.all():
            if referral.is_completed or referral.is_withdrawn or referral.purpose == "FOR_INFO":
                continue
            if any(
                item.is_active_step
                and item.status in ("PENDING", "RECEIVED", "WAITING_TURN")
                for item in referral.recipients.all()
            ):
                return "بانتظار إجراء الإحالة"

        memos = list(subject.memos.all())
        latest_memo = max(memos, key=lambda item: item.created_at, default=None)
        if latest_memo and latest_memo.status != "APPROVED":
            return "مذكرة عرض قيد الإعداد / الاعتماد"

        if latest_memo and latest_memo.status == "APPROVED" and subject.transaction_type.requires_decision:
            decisions = [item for item in subject.decisions.all() if item.status != "CANCELLED"]
            if not decisions:
                return "قرار جديد"
            latest_decision = max(decisions, key=lambda item: item.created_at)
            if latest_decision.status in ("DRAFT", "UNDER_REVIEW"):
                return "قرار جديد قيد الإعداد / المراجعة"

        return subject.get_status_display()

    @staticmethod
    @transaction.atomic
    def create_subject(
        *,
        title: str,
        description: str = "",
        transaction_type,
        sector,
        org_unit,
        confidentiality,
        priority,
        created_by,
        current_owner=None,
        applicant_name: str = "",
        external_source: str = "",
        keywords: str = "",
        status: str = Subject.Status.NEW,
        due_date=None,
    ) -> Subject:
        WorkflowTemplateVersion = apps.get_model("workflow", "WorkflowTemplateVersion")
        active_template = (
            WorkflowTemplateVersion.objects.filter(
                template__transaction_type=transaction_type,
                is_active=True,
            )
            .order_by("-version_number")
            .first()
        )
        if due_date is None and getattr(priority, "sla_days", None):
            due_date = timezone.localdate() + timezone.timedelta(days=priority.sla_days)
        internal_number = SystemSequence.next_number("SUBJECT", "SUB")
        subject = Subject.objects.create(
            internal_number=internal_number,
            title=title,
            description=description,
            transaction_type=transaction_type,
            sector=sector,
            org_unit=org_unit,
            applicant_name=applicant_name,
            external_source=external_source,
            confidentiality=confidentiality,
            priority=priority,
            due_date=due_date,
            status=status,
            current_owner=current_owner or created_by,
            created_by=created_by,
            workflow_template_version=active_template,
            keywords=keywords,
        )
        SubjectStatusHistory.objects.create(
            subject=subject,
            from_status="",
            to_status=status,
            changed_by=created_by,
            reason="إنشاء الموضوع",
        )
        delegation = PermissionService.get_acting_delegation(created_by, "SUBJECT_CREATE", subject=subject)
        AuditService.record_activity(
            subject=subject,
            action_type="SUBJECT_CREATED",
            actor_user=created_by,
            acting_on_behalf_of=delegation.delegator if delegation else None,
            delegation=delegation,
            description=f"تم إنشاء الموضوع ({subject.internal_number}): {subject.title}",
        )
        return subject

    @staticmethod
    @transaction.atomic
    def update_subject_with_lock(subject_id: int, expected_version: int, user, **fields) -> Subject:
        subject = Subject.objects.select_for_update().get(id=subject_id)
        if subject.version_lock != expected_version:
            raise OptimisticLockError(
                "تم تعديل هذا الموضوع بواسطة مستخدم آخر أثناء عملك. يرجى إعادة تحميل الصفحة ومراجعة البيانات قبل الحفظ."
            )
        for key, value in fields.items():
            setattr(subject, key, value)
        subject.version_lock += 1
        subject.last_action_at = timezone.now()
        subject.save()
        AuditService.record_activity(
            subject=subject,
            action_type="SUBJECT_UPDATED",
            actor_user=user,
            description="تحديث البيانات الوصفية للموضوع",
        )
        return subject

    @staticmethod
    @transaction.atomic
    def suspend_subject(
        *,
        subject: Subject,
        user,
        reason_details: str,
        required_from: str,
        required_item: str,
        follow_up_owner=None,
        reason_ref=None,
        expected_follow_up_date=None,
        committee=None,
    ) -> SubjectSuspension:
        if subject.status == Subject.Status.CLOSED:
            raise ValidationError("لا يمكن تعليق موضوع مغلق؛ أعد فتحه أولاً بصلاحية مناسبة.")

        transition_subject(
            subject,
            Subject.Status.SUSPENDED,
            user,
            reason=f"تعليق للاستيفاء: {required_item}" + (f" ({required_from})" if required_from else ""),
        )
        suspension = SubjectSuspension.objects.create(
            subject=subject,
            reason_ref=reason_ref,
            reason_details=reason_details,
            required_from=required_from,
            required_item=required_item,
            committee=committee,
            suspended_by=user,
            follow_up_owner=follow_up_owner or user,
            expected_follow_up_date=expected_follow_up_date,
        )
        AuditService.record_activity(
            subject=subject,
            action_type="SUBJECT_SUSPENDED",
            actor_user=user,
            description=f"تم تعليق الموضوع لحين استيفاء ({required_item})" + (f" من ({required_from})" if required_from else "") + f". السبب: {reason_details}",
            metadata={"action": "تعليق", "status": subject.get_status_display(), "status_code": subject.status},
        )
        return suspension

    @staticmethod
    @transaction.atomic
    def fulfill_suspension(*, suspension: SubjectSuspension, user, fulfillment_notes: str, resume_status: str = Subject.Status.IN_PROGRESS):
        if suspension.is_fulfilled:
            raise ValidationError("تم تسجيل الاستيفاء لهذا التعليق مسبقاً.")

        allowed_resume = {
            Subject.Status.IN_PROGRESS,
            Subject.Status.UNDER_REVIEW,
            Subject.Status.AWAITING_APPROVAL,
            Subject.Status.AWAITING_COMMITTEE,
        }
        if resume_status not in allowed_resume:
            resume_status = Subject.Status.IN_PROGRESS

        suspension.is_fulfilled = True
        suspension.fulfilled_at = timezone.now()
        suspension.fulfilled_by = user
        suspension.fulfillment_notes = fulfillment_notes
        suspension.save(update_fields=["is_fulfilled", "fulfilled_at", "fulfilled_by", "fulfillment_notes"])

        subject = suspension.subject
        transition_subject(
            subject,
            resume_status,
            user,
            reason=f"استيفاء المطلوب واستئناف العمل: {fulfillment_notes}",
        )
        AuditService.record_activity(
            subject=subject,
            action_type="SUSPENSION_FULFILLED",
            actor_user=user,
            description=f"تم استيفاء المطلوب ({suspension.required_item}): {fulfillment_notes}",
            metadata={"action": "استئناف بعد التعليق", "status": subject.get_status_display(), "status_code": subject.status},
        )
        return subject

    @staticmethod
    def validate_closure_requirements(subject: Subject) -> list[str]:
        """التحقق من شروط الإغلاق الرسمية للموضوع قبل السماح بإغلاقه."""
        errors = []
        Task = apps.get_model("workflow", "Task")
        Decision = apps.get_model("decisions", "Decision")
        DecisionExecutionItem = apps.get_model("decisions", "DecisionExecutionItem")

        if subject.status == Subject.Status.SUSPENDED:
            errors.append("الموضوع معلق حالياً ولا يجوز إغلاقه قبل استيفاء أو إلغاء التعليق.")

        open_tasks = Task.objects.filter(subject=subject).exclude(
            status__in=["COMPLETED", "CANCELLED", "REJECTED"]
        )
        if open_tasks.exists():
            errors.append(f"توجد {open_tasks.count()} مهام غير مكتملة مرتبطة بالموضوع.")

        if subject.transaction_type.requires_decision:
            decisions = Decision.objects.filter(subject=subject).exclude(status="CANCELLED")
            if not decisions.exists():
                errors.append("نوع المعاملة يتطلب صدور قرار إداري قبل الإغلاق.")
            else:
                if subject.transaction_type.requires_execution_proof:
                    incomplete_exec = DecisionExecutionItem.objects.filter(
                        decision__in=decisions
                    ).exclude(execution_status="COMPLETED")
                    if incomplete_exec.exists() or DecisionExecutionItem.objects.filter(decision__in=decisions).count() == 0:
                        errors.append("لم يكتمل تسجيل تنفيذ القرار لدى جميع الجهات المكلفة.")

        # طلب البيان الوارد يخرج في النهاية كرد صادر مرتبط بنفس الموضوع (قاعدة المستخدم: وطبعاً لو في بيان وارد وخلصته بطلعه في النهاية كصادر).
        # لا ينطبق على موضوع بدأ صادراً. الإغلاق الاستثنائي يبقى متاحاً بصلاحيته؛ ولا تُفرض القاعدة على أنواع أخرى.
        if getattr(subject.transaction_type, "code", "") == "EXTERNAL_REQUEST" and subject.pk:
            items = subject.outgoing_items.all()
            if not items.filter(is_origin=True).exists() and not items.filter(kind="RESPONSE", sent_at__isnull=False).exists():
                errors.append("طلب البيان لم يخرج ردّه الصادر المرتبط بعد: سجّل الرد الصادر (بعد إرساله فعلاً) قبل الإغلاق.")

        waiting = Subject.objects.filter(id=subject.id, outgoing_items__kind="REQUEST", outgoing_items__sent_at__isnull=False, outgoing_items__reply_received_at__isnull=True).values_list("outgoing_items__recipient_entity", flat=True)
        for entity in waiting:
            errors.append(f"الموضوع بانتظار رد/استيفاء من ({entity}) على مراسلة صادرة.")

        return errors

    @classmethod
    @transaction.atomic
    def close_subject(
        cls,
        *,
        subject: Subject,
        user,
        closure_notes: str = "",
        exceptional: bool = False,
    ) -> Subject:
        if subject.status == Subject.Status.CLOSED:
            raise ValidationError("الموضوع مغلق بالفعل.")

        if not PermissionService.user_has_permission(
            user, "SUBJECT_CLOSE", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject
        ):
            raise PermissionDenied("ليس لديك صلاحية إغلاق الموضوع.")

        unmet = cls.validate_closure_requirements(subject)
        if unmet:
            if not exceptional:
                raise ValidationError("تعذر الإغلاق الرسمي لعدم استيفاء الشروط: " + " | ".join(unmet))
            if not PermissionService.user_has_permission(
                user, "SUBJECT_EXCEPTIONAL_CLOSE", sector=subject.sector, subject=subject
            ):
                raise PermissionDenied("الإغلاق الاستثنائي يتطلب صلاحية خاصة.")
            if not closure_notes.strip():
                raise ValidationError("يجب تسجيل مبرر واضح عند الإغلاق الاستثنائي.")

        transition_subject(
            subject,
            Subject.Status.CLOSED,
            user,
            reason=f"{'إغلاق استثنائي' if exceptional else 'إغلاق رسمي وأرشفة'}: {closure_notes}",
        )
        subject.retention_status = Subject.RetentionStatus.ARCHIVED
        subject.closed_at = timezone.now()
        subject.closed_by = user
        subject.closure_notes = closure_notes
        subject.is_exceptional_closure = exceptional
        subject.save(
            update_fields=[
                "retention_status",
                "closed_at",
                "closed_by",
                "closure_notes",
                "is_exceptional_closure",
            ]
        )

        AuditService.record_activity(
            subject=subject,
            action_type="SUBJECT_CLOSED",
            actor_user=user,
            description=f"تم {'إغلاق الموضوع استثنائياً وأرشفته' if exceptional else 'إغلاق الموضوع رسمياً وأرشفته'}. {closure_notes}",
            metadata={"action": "إغلاق الموضوع", "status": subject.get_status_display(), "status_code": subject.status},
        )
        AuditService.log_audit(
            actor=user,
            action="SUBJECT_CLOSED",
            model_name="Subject",
            object_id=subject.id,
            after_state={"exceptional": exceptional, "notes": closure_notes, "retention_status": subject.retention_status},
        )
        return subject

    @staticmethod
    @transaction.atomic
    def reopen_subject(*, subject: Subject, user, reason: str) -> Subject:
        if subject.status != Subject.Status.CLOSED:
            raise ValidationError("لا يمكن إعادة فتح موضوع غير مغلق.")
        if not PermissionService.user_has_permission(
            user, "SUBJECT_REOPEN", sector=subject.sector, subject=subject
        ):
            raise PermissionDenied("ليس لديك صلاحية إعادة فتح الموضوعات المغلقة.")
        if not reason.strip():
            raise ValidationError("يجب تسجيل سبب إعادة الفتح.")

        # نحتفظ بـ closed_at و closed_by التاريخية ولا نمحوها، مع تغيير الحالة إلى REOPENED
        transition_subject(
            subject,
            Subject.Status.REOPENED,
            user,
            reason=f"إعادة فتح: {reason}",
        )
        subject.retention_status = Subject.RetentionStatus.ACTIVE
        subject.save(update_fields=["retention_status"])

        AuditService.record_activity(
            subject=subject,
            action_type="SUBJECT_REOPENED",
            actor_user=user,
            description=f"أُعيد فتح الموضوع مع الاحتفاظ بسجل الإغلاق السابق. السبب: {reason}",
        )
        return subject
