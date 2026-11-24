import logging
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from accounts.services import PermissionService
from audit.services import AuditService
from core.models import SystemSequence
from notifications.models import Notification
from notifications.services import NotificationService
from subjects.models import Subject
from subjects.services import transition_subject
from .models import Decision, DecisionDistribution, DecisionExecutionItem

logger = logging.getLogger(__name__)


class DecisionService:
    @staticmethod
    @transaction.atomic
    def create_decision_draft(
        *,
        subject: Subject,
        decision_type: str,
        title: str,
        body: str,
        issuing_authority: str,
        approving_authority: str,
        created_by,
        committee_item=None,
        idempotency_key: str | None = None,
    ) -> Decision:
        if idempotency_key:
            existing = Decision.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing

        dec_num = SystemSequence.next_number("DECISION", "DEC")
        decision = Decision.objects.create(
            decision_number=dec_num,
            decision_type=decision_type,
            subject=subject,
            committee_item=committee_item,
            title=title,
            body=body,
            issuing_authority=issuing_authority,
            approving_authority=approving_authority,
            status=Decision.Status.DRAFT,
            created_by=created_by,
            idempotency_key=idempotency_key or None,
        )
        AuditService.record_activity(
            subject=subject,
            action_type="DECISION_DRAFTED",
            actor_user=created_by,
            description=f"تم إعداد مشروع القرار رقم {decision.decision_number}: {decision.title}",
        )
        return decision

    @staticmethod
    @transaction.atomic
    def approve_and_issue(*, decision: Decision, user, issue_immediately: bool = True) -> Decision:
        if not PermissionService.user_has_permission(
            user,
            "DECISION_APPROVE",
            sector=decision.subject.sector,
            confidentiality_rank=decision.subject.confidentiality.rank,
            subject=decision.subject,
        ):
            raise PermissionDenied("ليس لديك صلاحية اعتماد وإصدار القرارات.")

        now = timezone.now()
        decision.approved_by = user
        decision.approved_at = now
        decision.status = Decision.Status.ISSUED if issue_immediately else Decision.Status.APPROVED
        if issue_immediately:
            decision.issued_date = now.date()
            transition_subject(
                decision.subject,
                Subject.Status.DECISION_ISSUED,
                user,
                reason=f"إصدار القرار رقم {decision.decision_number}",
            )
        decision.save()

        AuditService.record_activity(
            subject=decision.subject,
            action_type="DECISION_ISSUED" if issue_immediately else "DECISION_APPROVED",
            actor_user=user,
            description=f"{'اعتماد وإصدار' if issue_immediately else 'اعتماد'} القرار رقم {decision.decision_number}",
        )
        AuditService.log_audit(
            actor=user,
            action="DECISION_ISSUED",
            model_name="Decision",
            object_id=decision.id,
            after_state={"decision_number": decision.decision_number, "status": decision.status},
        )
        return decision

    @staticmethod
    @transaction.atomic
    def distribute_and_assign_execution(
        *,
        decision: Decision,
        user,
        distribution_units: list,
        execution_assignments: list[dict],
    ) -> Decision:
        if not PermissionService.user_has_permission(
            user,
            "DECISION_APPROVE",
            sector=decision.subject.sector,
            confidentiality_rank=decision.subject.confidentiality.rank,
            subject=decision.subject,
        ):
            raise PermissionDenied("ليس لديك صلاحية توزيع القرار أو تكليف جهات التنفيذ.")

        if decision.status not in (
            Decision.Status.APPROVED,
            Decision.Status.ISSUED,
            Decision.Status.DISTRIBUTING,
            Decision.Status.EXECUTING,
        ):
            raise ValidationError("يجب اعتماد القرار وإصداره قبل التوزيع والتنفيذ.")

        if not getattr(user, "is_superuser", False) and not PermissionService.is_org_wide_manager(user):
            for unit in distribution_units:
                if unit.sector_id != decision.subject.sector_id:
                    raise PermissionDenied("لا يمكن توزيع القرار على وحدة خارج قطاع الموضوع.")
            for item in execution_assignments:
                if item["unit"].sector_id != decision.subject.sector_id:
                    raise PermissionDenied("لا يمكن تكليف وحدة تنفيذية خارج قطاع الموضوع.")

        for unit in distribution_units:
            DecisionDistribution.objects.get_or_create(decision=decision, target_unit=unit)

        created_exec_items = []
        for item in execution_assignments:
            exec_item = DecisionExecutionItem.objects.create(
                decision=decision,
                assigned_unit=item["unit"],
                assigned_user=item["user"],
                required_action=item["required_action"],
                due_date=item.get("due_date"),
            )
            created_exec_items.append(exec_item)

        if created_exec_items:
            dec_id = decision.id
            dec_num = decision.decision_number
            subj = decision.subject

            def _notify_executors():
                for ex in created_exec_items:
                    try:
                        NotificationService.notify(
                            recipient=ex.assigned_user,
                            subject=subj,
                            category=Notification.Category.DECISION,
                            title=f"تكليف بتنفيذ القرار {dec_num}",
                            message=f"المطلوب: {ex.required_action}",
                            link_url=f"/decisions/{dec_id}/",
                        )
                    except Exception:
                        logger.exception("تعذر إرسال إشعار تنفيذ القرار %s", dec_num)

            transaction.on_commit(_notify_executors)

        decision.status = Decision.Status.EXECUTING if execution_assignments else Decision.Status.DISTRIBUTING
        decision.save(update_fields=["status"])

        target_subject_status = (
            Subject.Status.FINAL_EXECUTION if execution_assignments else Subject.Status.DISTRIBUTING
        )
        if decision.subject.status != target_subject_status:
            transition_subject(
                decision.subject,
                target_subject_status,
                user,
                reason=f"توزيع القرار رقم {decision.decision_number}",
            )
        else:
            decision.subject.last_action_at = timezone.now()
            decision.subject.save(update_fields=["last_action_at"])

        AuditService.record_activity(
            subject=decision.subject,
            action_type="DECISION_DISTRIBUTED",
            actor_user=user,
            description=f"توزيع القرار {decision.decision_number} وإنشاء {len(execution_assignments)} مهام تنفيذية",
        )
        return decision

    @staticmethod
    @transaction.atomic
    def complete_execution_item(
        *,
        exec_item: DecisionExecutionItem,
        user,
        execution_result: str,
        proof_document=None,
    ) -> Decision:
        is_authorized = getattr(user, "is_superuser", False) or exec_item.assigned_user_id == user.id
        if not is_authorized:
            delegation = PermissionService.get_acting_delegation(
                user, "DECISION_CREATE", subject=exec_item.decision.subject
            )
            is_authorized = bool(delegation and delegation.delegator_id == exec_item.assigned_user_id)
        if not is_authorized:
            raise PermissionDenied("تسجيل إتمام تنفيذ القرار مقتصر على الموظف المكلف بالتنفيذ فقط.")

        exec_item.execution_status = DecisionExecutionItem.ExecutionStatus.COMPLETED
        exec_item.execution_result = execution_result
        exec_item.proof_document = proof_document
        exec_item.completed_at = timezone.now()
        exec_item.save()

        decision = exec_item.decision
        AuditService.record_activity(
            subject=decision.subject,
            action_type="DECISION_EXECUTION_RECORDED",
            actor_user=user,
            description=f"تنفيذ بند القرار {decision.decision_number} ({exec_item.assigned_unit.name}): {execution_result}",
        )

        # إذا اكتملت جميع بنود التنفيذ، تصبح حالة القرار مكتمل التنفيذ وحالة الموضوع مكتمل
        remaining = decision.execution_items.exclude(
            execution_status=DecisionExecutionItem.ExecutionStatus.COMPLETED
        ).exists()
        if not remaining:
            decision.status = Decision.Status.COMPLETED
            decision.save(update_fields=["status"])
            if decision.subject.status != Subject.Status.COMPLETED:
                transition_subject(
                    decision.subject,
                    Subject.Status.COMPLETED,
                    user,
                    reason=f"اكتمال تنفيذ القرار رقم {decision.decision_number}",
                )

        return decision
