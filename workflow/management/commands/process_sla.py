"""
أمر الإدارة الدوري لمعالجة مهل الاستحقاق (SLA):
- إرسال تذكير قبل تاريخ الاستحقاق بيوم واحد دون تكرار (last_reminded_at).
- تصعيد الإحالات والمهام المتأخرة بإشعار المدير المباشر وتسجيل ActivityLog دون تكرار (escalated_at).
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from audit.services import AuditService
from notifications.models import Notification
from notifications.services import NotificationService
from workflow.models import Referral, ReferralRecipient, Task


class Command(BaseCommand):
    help = "معالجة تذكيرات وتصعيدات SLA للإحالات والمهام المستحقة دون تكرار."

    def handle(self, *args, **options):
        now = timezone.now()
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)

        reminded_referrals = 0
        reminded_tasks = 0
        escalated_referrals = 0
        escalated_tasks = 0

        # 1) تذكير قبل الاستحقاق بيوم واحد للإحالات النشطة
        due_soon_refs = (
            Referral.objects.filter(
                is_completed=False,
                is_withdrawn=False,
                due_date=tomorrow,
                last_reminded_at__isnull=True,
            )
            .select_related("subject__confidentiality", "subject__priority", "referred_by", "coordinator")
            .prefetch_related(
                "recipients__target_user",
                "recipients__target_unit__manager_employee__user_account",
            )
        )
        for ref in due_soon_refs:
            targets = set()
            for rec in ref.recipients.all():
                if rec.is_active_step and rec.status in (
                    ReferralRecipient.RecipientStatus.PENDING,
                    ReferralRecipient.RecipientStatus.RECEIVED,
                ):
                    if rec.target_user and rec.target_user.is_active:
                        targets.add(rec.target_user)
                    elif rec.target_unit and getattr(rec.target_unit, "manager_employee", None):
                        mgr_user = getattr(rec.target_unit.manager_employee, "user_account", None)
                        if mgr_user and mgr_user.is_active:
                            targets.add(mgr_user)
            if not targets and (ref.coordinator or ref.referred_by):
                targets.add(ref.coordinator or ref.referred_by)

            prio_code = getattr(ref.subject.priority, "code", "NORMAL") if ref.subject.priority_id else "NORMAL"
            with transaction.atomic():
                for target_user in targets:
                    NotificationService.notify(
                        recipient=target_user,
                        subject=ref.subject,
                        category=Notification.Category.DEADLINE,
                        priority=prio_code,
                        title=f"تذكير استحقاق إحالة غداً ({ref.subject.internal_number})",
                        message=f"موعد استحقاق الإحالة على الموضوع «{ref.subject.title}» غداً ({ref.due_date}).",
                        link_url=f"/subjects/{ref.subject_id}/",
                    )
                ref.last_reminded_at = now
                ref.save(update_fields=["last_reminded_at"])
                reminded_referrals += 1

        # 2) تذكير قبل الاستحقاق بيوم واحد للمهام المفتوحة
        closed_task_statuses = [
            Task.TaskStatus.COMPLETED,
            Task.TaskStatus.CANCELLED,
            Task.TaskStatus.REJECTED,
        ]
        due_soon_tasks = (
            Task.objects.filter(
                due_date=tomorrow,
                last_reminded_at__isnull=True,
            )
            .exclude(status__in=closed_task_statuses)
            .select_related("subject__confidentiality", "priority", "assigned_to")
        )
        for task in due_soon_tasks:
            prio_code = getattr(task.priority, "code", "NORMAL") if task.priority_id else "NORMAL"
            with transaction.atomic():
                if task.assigned_to and task.assigned_to.is_active:
                    NotificationService.notify(
                        recipient=task.assigned_to,
                        subject=task.subject,
                        category=Notification.Category.DEADLINE,
                        priority=prio_code,
                        title=f"تذكير استحقاق مهمة غداً ({task.subject.internal_number})",
                        message=f"موعد استحقاق المهمة «{task.title}» غداً ({task.due_date}).",
                        link_url=f"/subjects/{task.subject_id}/",
                    )
                task.last_reminded_at = now
                task.save(update_fields=["last_reminded_at"])
                reminded_tasks += 1

        # 3) تصعيد الإحالات المتجاوزة للاستحقاق (إشعار المدير المباشر + ActivityLog)
        overdue_refs = (
            Referral.objects.filter(
                is_completed=False,
                is_withdrawn=False,
                due_date__lt=today,
                escalated_at__isnull=True,
            )
            .select_related(
                "subject__confidentiality",
                "subject__priority",
                "subject__current_owner",
                "subject__created_by",
                "referred_by",
                "coordinator",
            )
            .prefetch_related(
                "recipients__target_user__employee__current_unit__manager_employee__user_account",
                "recipients__target_unit__manager_employee__user_account",
            )
        )
        for ref in overdue_refs:
            managers = set()
            for rec in ref.recipients.all():
                if rec.is_active_step and rec.status in (
                    ReferralRecipient.RecipientStatus.PENDING,
                    ReferralRecipient.RecipientStatus.RECEIVED,
                ):
                    if rec.target_user:
                        mgr = NotificationService.get_direct_manager(rec.target_user)
                        if mgr:
                            managers.add(mgr)
                    elif rec.target_unit and getattr(rec.target_unit, "manager_employee", None):
                        unit_mgr = getattr(rec.target_unit.manager_employee, "user_account", None)
                        if unit_mgr and unit_mgr.is_active:
                            parent_mgr = NotificationService.get_direct_manager(unit_mgr)
                            managers.add(parent_mgr or unit_mgr)

            if not managers and ref.subject.current_owner:
                owner_mgr = NotificationService.get_direct_manager(ref.subject.current_owner)
                if owner_mgr:
                    managers.add(owner_mgr)
            if not managers and (ref.coordinator or ref.referred_by):
                managers.add(ref.coordinator or ref.referred_by)

            actor = (
                next(iter(managers), None)
                or ref.referred_by
                or ref.subject.current_owner
                or ref.subject.created_by
            )
            with transaction.atomic():
                for mgr in managers:
                    NotificationService.notify(
                        recipient=mgr,
                        subject=ref.subject,
                        category=Notification.Category.ESCALATION_OVERDUE,
                        priority="URGENT",
                        title=f"تصعيد SLA — تأخر إحالة ({ref.subject.internal_number})",
                        message=f"تجاوزت الإحالة على الموضوع «{ref.subject.title}» موعد الاستحقاق ({ref.due_date}).",
                        link_url=f"/subjects/{ref.subject_id}/",
                    )
                if actor:
                    AuditService.record_activity(
                        subject=ref.subject,
                        action_type="SLA_ESCALATED",
                        actor_user=actor,
                        description=f"تصعيد تلقائي لتجاوز مهلة استحقاق الإحالة رقم {ref.id} (الاستحقاق: {ref.due_date}).",
                    )
                ref.escalated_at = now
                ref.save(update_fields=["escalated_at"])
                escalated_referrals += 1

        # 4) تصعيد المهام المتجاوزة للاستحقاق (إشعار المدير المباشر + ActivityLog)
        overdue_tasks = (
            Task.objects.filter(
                due_date__lt=today,
                escalated_at__isnull=True,
            )
            .exclude(status__in=closed_task_statuses)
            .select_related(
                "subject__confidentiality",
                "subject__current_owner",
                "subject__created_by",
                "assigned_to__employee__current_unit__manager_employee__user_account",
                "assigned_by",
            )
        )
        for task in overdue_tasks:
            manager = NotificationService.get_direct_manager(task.assigned_to) or task.assigned_by
            actor = manager or task.assigned_by or task.assigned_to or task.subject.created_by
            with transaction.atomic():
                if manager:
                    NotificationService.notify(
                        recipient=manager,
                        subject=task.subject,
                        category=Notification.Category.ESCALATION_OVERDUE,
                        priority="URGENT",
                        title=f"تصعيد SLA — تأخر مهمة ({task.subject.internal_number})",
                        message=f"تجاوزت المهمة «{task.title}» المسندة إلى {task.assigned_to} موعد الاستحقاق ({task.due_date}).",
                        link_url=f"/subjects/{task.subject_id}/",
                    )
                if actor:
                    AuditService.record_activity(
                        subject=task.subject,
                        action_type="SLA_ESCALATED",
                        actor_user=actor,
                        description=f"تصعيد تلقائي لتجاوز مهلة استحقاق المهمة «{task.title}» (الاستحقاق: {task.due_date}).",
                    )
                task.escalated_at = now
                task.save(update_fields=["escalated_at"])
                escalated_tasks += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"SLA: تذكير ({reminded_referrals} إحالة، {reminded_tasks} مهمة) | "
                f"تصعيد ({escalated_referrals} إحالة، {escalated_tasks} مهمة)"
            )
        )
