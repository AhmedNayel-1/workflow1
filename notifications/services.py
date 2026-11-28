"""
خدمة الإشعارات المعزولة:
- تتحقق من صلاحية المستلم لرؤية الموضوع قبل تضمين أي تفاصيل.
- لا تؤدي أخطاء الإشعارات أبداً إلى إفشال حفظ الإحالة أو القرار.
"""
from accounts.services import PermissionService
from core.models import SystemErrorLog
from .models import Notification


class NotificationService:
    LEVEL_BY_ROLE = {
        "CHAIRMAN": "L1",
        "SECTOR_HEAD": "L2",
        "GENERAL_MANAGER": "L3",
        "SUPERVISOR": "L4",
        "SPECIALIST": "L5",
        "SECRETARIAT": "L6",
        "SYSTEM_ADMIN": "L0",
    }

    @classmethod
    def infer_user_level(cls, user, sector=None) -> str:
        if user is None:
            return "L5"
        if getattr(user, "is_superuser", False) or getattr(user, "is_system_admin", False):
            return "L1"
        role_codes = PermissionService.get_effective_role_codes(user, sector=sector)
        for role_code in ("CHAIRMAN", "SECTOR_HEAD", "GENERAL_MANAGER", "SUPERVISOR", "SPECIALIST", "SECRETARIAT"):
            if role_code in role_codes:
                return cls.LEVEL_BY_ROLE[role_code]
        if getattr(user, "is_secretariat", False):
            return "L6"
        return "L5"

    @staticmethod
    def default_reason_for_level(category: str, target_level: str) -> str:
        reasons = {
            Notification.Category.REFERRAL: f"مخصص للمستوى ({target_level}): إحالة واردة بانتظار التنفيذ والمتابعة.",
            Notification.Category.INCOMING_REFERRAL: f"مخصص للمستوى ({target_level}): إحالة جديدة أو رد وارد بانتظار الإجراء.",
            Notification.Category.REPLY_MEMO: f"مخصص للمستوى ({target_level}): متابعة الردود والمذكرات المرفوعة.",
            Notification.Category.APPROVAL_NEEDED: f"مخصص للمستوى ({target_level}): مطلوب المراجعة والاعتماد الرسمي.",
            Notification.Category.DECISION_TASK: f"مخصص للمستوى ({target_level}): قرار إداري أو تكليف تنفيذي مسند.",
            Notification.Category.ESCALATION_OVERDUE: f"مخصص للمستوى ({target_level}): تصعيد تأخير تجاوز مهلة الاستحقاق.",
            Notification.Category.FULFILLMENT: f"مخصص للمستوى ({target_level}): إشعار استيفاء تعليق واستئناف المعاملة.",
            Notification.Category.TASK: f"مخصص للمستوى ({target_level}): مهمة تنفيذية مرتبطة بالموضوع.",
            Notification.Category.DEADLINE: f"مخصص للمستوى ({target_level}): تنبيه موعد استحقاق.",
            Notification.Category.SUSPENSION: f"مخصص للمستوى ({target_level}): تعليق معاملة للاستيفاء.",
            Notification.Category.DECISION: f"مخصص للمستوى ({target_level}): إصدار قرار إداري.",
        }
        return reasons.get(category, f"تنبيه نظام مخصص للمستوى ({target_level}).")

    @staticmethod
    def get_direct_manager(user):
        """إرجاع حساب المستخدم للمدير المباشر عبر manager_employee أو الأدوار الإشرافية بالوحدة والتسلسل الهرمي."""
        if user is None:
            return None
        from accounts.models import User as AccountUser

        unit = getattr(user, "current_unit", None)
        visited = set()
        chain = []
        while unit is not None and unit.id not in visited:
            visited.add(unit.id)
            chain.append(unit)
            mgr_emp = getattr(unit, "manager_employee", None)
            if mgr_emp is not None:
                mgr_user = getattr(mgr_emp, "user_account", None)
                if mgr_user is not None and mgr_user.is_active and mgr_user.id != user.id:
                    return mgr_user
            unit = unit.parent

        # في حال عدم ربط manager_employee على الوحدة، نبحث في الأدوار القيادية على نفس الوحدة ثم الوحدات الأب
        manager_role_codes = ("SUPERVISOR", "GENERAL_MANAGER", "SECTOR_HEAD", "CHAIRMAN")
        for cursor_unit in chain:
            for role_code in manager_role_codes:
                mgr_user = (
                    AccountUser.objects.filter(
                        is_active=True,
                        employee__current_unit=cursor_unit,
                        role_assignments__is_active=True,
                        role_assignments__role__code=role_code,
                    )
                    .exclude(id=user.id)
                    .order_by("id")
                    .first()
                )
                if mgr_user is not None:
                    return mgr_user
        return None

    @classmethod
    def notify(
        cls,
        *,
        recipient,
        title: str,
        message: str,
        category: str = Notification.Category.SYSTEM,
        subject=None,
        link_url: str = "",
        priority: str = "NORMAL",
        target_level: str = "",
        reason_for_level: str = "",
    ):
        try:
            sector = getattr(subject, "sector", None) if subject is not None else None
            resolved_level = target_level or cls.infer_user_level(recipient, sector=sector)
            resolved_reason = reason_for_level or cls.default_reason_for_level(category, resolved_level)

            if subject is not None:
                if not PermissionService.can_view_subject(recipient, subject):
                    return None
                if subject.confidentiality.overrides_hierarchy:
                    # عدم كشف تفاصيل الموضوع الحساسة في نص التنبيه
                    title = f"إشعار معاملة مصنفة ({subject.internal_number})"
                    message = "توجد معاملة ذات درجة سرية خاصة تتطلب متابعتك داخل المنظومة."
                    resolved_reason = f"تنبيه سري مقيد للمستوى ({resolved_level}) المصرح له."

            return Notification.objects.create(
                recipient=recipient,
                subject=subject,
                category=category,
                priority=priority or "NORMAL",
                target_level=resolved_level,
                reason_for_level=resolved_reason[:200],
                title=title,
                message=message,
                link_url=link_url,
            )
        except Exception as exc:
            SystemErrorLog.objects.create(
                component="notifications",
                operation="send_notification",
                error_message=str(exc),
                reference_type="Subject" if subject else "",
                reference_id=str(subject.id) if subject else "",
            )
            return None

