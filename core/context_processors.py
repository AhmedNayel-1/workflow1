from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from accounts.models import Delegation, User
from accounts.services import PermissionService
from chat.models import ChatMessage
from core.models import (
    ConfidentialityLevel,
    DocumentType,
    MemoRecipientRef,
    MemoTypeRef,
    PriorityLevel,
    TransactionType,
)
from notifications.models import Notification
from notifications.services import NotificationService
from organization.models import Company, OrgUnit, Sector
from subjects.models import Subject
from workflow.models import ReferralRecipient, Task


CLOSED_STATUSES = [
    Subject.Status.CLOSED,
    Subject.Status.COMPLETED,
    Subject.Status.CANCELLED,
    Subject.Status.REJECTED,
]


def get_user_overdue_alerts(user):
    """
    حساب التنبيهات الفورية للمعاملات والمراسلات والمهام التي تجاوزت تاريخ الاستحقاق،
    مع الالتزام الصارم بصلاحيات المستخدم والسرية الفائقة.
    """
    today = timezone.localdate()
    all_open_subjects = Subject.objects.select_related(
        "confidentiality", "transaction_type", "current_owner"
    ).exclude(status__in=CLOSED_STATUSES)
    visible_subjects = PermissionService.filter_visible_subjects(all_open_subjects, user)
    visible_ids = set(visible_subjects.values_list("id", flat=True))

    alerts = []

    for subj in visible_subjects:
        if subj.due_date and subj.due_date < today:
            days = (today - subj.due_date).days
            alerts.append({
                "kind": "SUBJECT",
                "kind_label": "معاملة / موضوع متأخر",
                "internal_number": subj.internal_number,
                "title": subj.title,
                "due_date": subj.due_date,
                "overdue_days": days,
                "confidentiality": subj.confidentiality.name,
                "is_top_secret": subj.confidentiality.overrides_hierarchy,
                "subject_id": subj.id,
                "url": f"/subjects/{subj.id}/",
                "owner_name": str(subj.current_owner),
            })

    unit = getattr(user, "current_unit", None)
    ref_q = Q(target_user=user)
    if unit:
        ref_q |= Q(target_unit=unit, target_user__isnull=True)

    overdue_refs = ReferralRecipient.objects.filter(
        ref_q,
        is_active_step=True,
        status__in=[
            ReferralRecipient.RecipientStatus.PENDING,
            ReferralRecipient.RecipientStatus.RECEIVED,
        ],
        referral__due_date__lt=today,
    ).select_related("referral__subject__confidentiality", "referral__referred_by")

    for rec in overdue_refs:
        subj = rec.referral.subject
        if subj.id in visible_ids and rec.referral.due_date:
            days = (today - rec.referral.due_date).days
            alerts.append({
                "kind": "REFERRAL",
                "kind_label": "إحالة مراسلة متأخرة",
                "internal_number": subj.internal_number,
                "title": f"{subj.title} (من: {rec.referral.referred_by})",
                "due_date": rec.referral.due_date,
                "overdue_days": days,
                "confidentiality": subj.confidentiality.name,
                "is_top_secret": subj.confidentiality.overrides_hierarchy,
                "subject_id": subj.id,
                "url": f"/subjects/{subj.id}/",
                "owner_name": str(rec.target_user or rec.target_unit or user),
            })

    overdue_tasks = (
        Task.objects.filter(assigned_to=user, due_date__lt=today, subject_id__in=visible_ids)
        .exclude(status__in=[Task.TaskStatus.COMPLETED, Task.TaskStatus.CANCELLED, Task.TaskStatus.REJECTED])
        .select_related("subject__confidentiality")
    )
    for task in overdue_tasks:
        days = (today - task.due_date).days
        alerts.append({
            "kind": "TASK",
            "kind_label": "مهمة متأخرة",
            "internal_number": task.subject.internal_number,
            "title": f"{task.title} ({task.subject.title})",
            "due_date": task.due_date,
            "overdue_days": days,
            "confidentiality": task.subject.confidentiality.name,
            "is_top_secret": task.subject.confidentiality.overrides_hierarchy,
            "subject_id": task.subject_id,
            "url": f"/subjects/{task.subject_id}/",
            "owner_name": str(user),
        })

    alerts.sort(key=lambda x: (-x["overdue_days"], x["internal_number"]))
    return alerts


def system_context(request):
    """توفير سياق Gmail الموحد (أعداد المجلدات، التنبيهات، نطاق الصلاحية، وبيانات نافذة الإنشاء)."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {
            "unread_notifications_count": 0,
            "active_delegations": [],
            "overdue_alerts": [],
            "overdue_alerts_count": 0,
            "today_date": timezone.localdate(),
            "user_access_scope": {},
            "gmail_folder_counts": {},
            "compose_meta": {},
            "memo_types": [],
            "memo_directed_targets": [],
            "chat_unread_count": 0,
            "user_level": "L5",
            "can_manage_users_scoped": False,
            "can_view_audit": False,
            "enable_dev_account_switcher": False,
            "dev_switch_users": [],
            "companies_list": [],
        }

    now = timezone.now()
    today = timezone.localdate()
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    active_delegations = list(
        Delegation.objects.filter(
            delegate=request.user,
            is_active=True,
            revoked_at__isnull=True,
            valid_from__lte=now,
            valid_to__gte=now,
        ).select_related("delegator", "scope_unit")
    )
    overdue_alerts = get_user_overdue_alerts(request.user)
    user_access_scope = PermissionService.describe_user_scope(request.user)

    # حساب أعداد مجلدات Gmail بدقة وفق صلاحيات المستخدم
    all_visible = list(
        PermissionService.filter_visible_subjects(
            Subject.objects.select_related("confidentiality", "org_unit", "sector", "transaction_type"),
            request.user,
        )
    )
    delegator_ids = [d.delegator_id for d in active_delegations]
    pending_subject_ids = set(
        ReferralRecipient.objects.filter(
            Q(target_user=request.user) | Q(target_user_id__in=delegator_ids),
            status=ReferralRecipient.RecipientStatus.PENDING,
            is_active_step=True,
        ).values_list("referral__subject_id", flat=True)
    )

    active_subjects = [s for s in all_visible if s.status != Subject.Status.CLOSED]
    inbox_count = sum(
        1 for s in active_subjects if PermissionService.can_act_on_subject(request.user, s) or s.id in pending_subject_ids
    )
    pending_count = sum(1 for s in active_subjects if s.id in pending_subject_ids)
    overdue_count = sum(1 for s in active_subjects if s.due_date and s.due_date < today)
    sent_count = sum(
        1
        for s in all_visible
        if not PermissionService.can_act_on_subject(request.user, s)
        and s.referrals.filter(referred_by=request.user).exists()
    )
    archive_count = sum(1 for s in all_visible if s.status == Subject.Status.CLOSED)
    open_tasks_count = (
        Task.objects.filter(assigned_to=request.user)
        .exclude(status__in=[Task.TaskStatus.COMPLETED, Task.TaskStatus.CANCELLED])
        .count()
    )

    chat_unread_count = (
        ChatMessage.objects.filter(conversation__members=request.user)
        .exclude(sender=request.user)
        .exclude(read_by=request.user)
        .distinct()
        .count()
    )
    user_level = NotificationService.infer_user_level(request.user)
    memo_types_list = list(MemoTypeRef.objects.filter(is_active=True))
    memo_targets_list = list(MemoRecipientRef.objects.filter(is_active=True))
    enable_switcher = bool(getattr(settings, "ENABLE_DEV_ACCOUNT_SWITCHER", False))
    dev_switch_users = []
    if enable_switcher:
        for u in User.objects.filter(is_active=True).select_related("employee__current_unit__sector").order_by("id"):
            lvl = NotificationService.infer_user_level(u)
            display_name = u.first_name or u.username
            role_label = u.job_display_title or ("مسؤول النظام" if u.is_superuser else "مستخدم")
            dev_switch_users.append({
                "id": u.id,
                "username": u.username,
                "level": lvl,
                "label": f"{display_name} ({lvl} · {role_label})",
            })

    can_manage_users_scoped = PermissionService.can_manage_users(request.user)
    can_view_audit = request.user.is_superuser or PermissionService.user_has_permission(request.user, "AUDIT_VIEW")
    companies_list = list(Company.objects.filter(is_active=True))

    _emp = getattr(request.user, "employee", None)
    _own_unit = getattr(_emp, "current_unit", None)
    _default_unit_id = _own_unit.id if _own_unit and _own_unit.is_active else None
    _default_sector_id = _own_unit.sector_id if _default_unit_id else None

    return {
        "unread_notifications_count": unread_count,
        "active_delegations": active_delegations,
        "overdue_alerts": overdue_alerts,
        "overdue_alerts_count": len(overdue_alerts),
        "today_date": today,
        "user_access_scope": user_access_scope,
        "user_level": user_level,
        "chat_unread_count": chat_unread_count,
        "memo_types": memo_types_list,
        "memo_directed_targets": memo_targets_list,
        "can_manage_users_scoped": can_manage_users_scoped,
        "can_view_audit": can_view_audit,
        "enable_dev_account_switcher": enable_switcher,
        "dev_switch_users": dev_switch_users,
        "companies_list": companies_list,
        "gmail_folder_counts": {
            "inbox": inbox_count,
            "pending": pending_count,
            "overdue": overdue_count,
            "sent": sent_count,
            "all": len(all_visible),
            "archive": archive_count,
            "open_tasks": open_tasks_count,
        },
        "compose_meta": {
            "transaction_types": TransactionType.objects.filter(is_active=True),
            "sectors": Sector.objects.filter(is_active=True),
            "org_units": OrgUnit.objects.filter(is_active=True).select_related("sector"),
            "confidentialities": ConfidentialityLevel.objects.filter(is_active=True),
            "priorities": PriorityLevel.objects.filter(is_active=True),
            "doc_types": DocumentType.objects.filter(is_active=True),
            "users": User.objects.filter(is_active=True).select_related("employee__current_unit"),
            "default_unit_id": _default_unit_id,
            "default_sector_id": _default_sector_id,
        },
    }
