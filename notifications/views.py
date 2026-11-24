import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.services import PermissionService
from workflow.models import Referral, Task
from .models import Notification
from .services import NotificationService


def _normalize_drawer_category(cat: str) -> str:
    mapping = {
        "REFERRAL": "INCOMING_REFERRAL",
        "INCOMING_REFERRAL": "INCOMING_REFERRAL",
        "REPLY_MEMO": "REPLY_MEMO",
        "FULFILLMENT": "REPLY_MEMO",
        "SUSPENSION": "REPLY_MEMO",
        "DECISION": "DECISION_TASK",
        "TASK": "DECISION_TASK",
        "DECISION_TASK": "DECISION_TASK",
        "APPROVAL_NEEDED": "APPROVAL_NEEDED",
        "DEADLINE": "ESCALATION_OVERDUE",
        "ESCALATION_OVERDUE": "ESCALATION_OVERDUE",
    }
    return mapping.get(cat, "INCOMING_REFERRAL")


@login_required
def notification_center(request):
    """مركز الإشعارات الذكية مع التصفية حسب الفئة وحجب تفاصيل السري للغاية."""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "mark_all_read":
            Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        elif action == "mark_read":
            notif = get_object_or_404(Notification, id=request.POST.get("notification_id"), recipient=request.user)
            notif.is_read = True
            notif.save(update_fields=["is_read"])
        return redirect("notifications:center")

    cat_filter = request.GET.get("cat", "ALL").strip().upper()
    user_level = NotificationService.infer_user_level(request.user)

    raw_notifications = Notification.objects.filter(recipient=request.user).select_related("subject__confidentiality")
    visible_notifications = []
    for n in raw_notifications:
        if n.subject is not None and not PermissionService.can_view_subject(request.user, n.subject):
            continue
        norm_cat = _normalize_drawer_category(n.category)
        if cat_filter != "ALL":
            if cat_filter == "DECISION_TASK" and norm_cat not in {"DECISION_TASK", "APPROVAL_NEEDED"}:
                continue
            elif cat_filter != "DECISION_TASK" and norm_cat != cat_filter:
                continue
        n.drawer_category = norm_cat
        visible_notifications.append(n)

    return render(
        request,
        "notifications/notification_center.html",
        {
            "notifications_list": visible_notifications,
            "cat_filter": cat_filter,
            "user_level": user_level,
        },
    )


@login_required
def drawer_state(request):
    """الحالة اللحظية للوحة التنبيهات الذكية في الشريط العلوي والجانبي."""
    user_level = NotificationService.infer_user_level(request.user)
    raw_notifications = Notification.objects.filter(recipient=request.user).select_related("subject__confidentiality")[:50]
    items = []
    seen_overdue_subjects = set()

    for n in raw_notifications:
        if n.subject is not None and not PermissionService.can_view_subject(request.user, n.subject):
            continue
        is_top_secret = bool(n.subject and n.subject.confidentiality.overrides_hierarchy)
        norm_cat = _normalize_drawer_category(n.category)
        if norm_cat == "ESCALATION_OVERDUE" and n.subject_id:
            seen_overdue_subjects.add(n.subject_id)
        items.append(
            {
                "id": n.id,
                "category": norm_cat,
                "raw_category": n.category,
                "category_label": n.get_category_display(),
                "priority": n.priority,
                "target_level": n.target_level or user_level,
                "reason_for_level": n.reason_for_level or NotificationService.default_reason_for_level(n.category, n.target_level or user_level),
                "title": n.title,
                "message": n.message,
                "link_url": n.link_url or (f"/subjects/{n.subject_id}/" if n.subject_id else "/notifications/"),
                "subject_id": n.subject_id,
                "is_top_secret": is_top_secret,
                "is_read": n.is_read,
                "is_live_escalation": False,
                "created_at": timezone.localtime(n.created_at).strftime("%Y-%m-%d %H:%M"),
            }
        )

    # قراءة التصعيدات المسجلة فعلياً من حقول escalated_at بدلاً من الحساب الحي المكلف
    today = timezone.localdate()
    escalated_refs = (
        Referral.objects.filter(
            escalated_at__isnull=False,
            is_completed=False,
            is_withdrawn=False,
        )
        .select_related("subject__confidentiality", "subject__current_owner", "referred_by")
        .prefetch_related("recipients__target_user", "recipients__target_unit")
    )
    for ref in escalated_refs:
        subj = ref.subject
        if ref.subject_id in seen_overdue_subjects:
            continue
        if not PermissionService.can_view_subject(request.user, subj):
            continue
        recs = list(ref.recipients.all())
        is_relevant = (
            request.user.is_superuser
            or ref.referred_by_id == request.user.id
            or ref.coordinator_id == request.user.id
            or subj.current_owner_id == request.user.id
            or any(
                r.target_user_id == request.user.id
                or (r.target_unit_id and request.user.current_unit and r.target_unit_id == request.user.current_unit.id)
                or (r.target_user and NotificationService.get_direct_manager(r.target_user) == request.user)
                for r in recs
            )
        )
        if not is_relevant:
            continue

        is_ts = bool(subj.confidentiality.overrides_hierarchy)
        overdue_days = max(1, (today - ref.due_date).days) if ref.due_date and ref.due_date < today else 0
        seen_overdue_subjects.add(ref.subject_id)
        items.append(
            {
                "id": f"escalated-ref-{ref.id}",
                "category": "ESCALATION_OVERDUE",
                "raw_category": "ESCALATION_OVERDUE",
                "category_label": "تصعيد إحالة متأخرة",
                "priority": "URGENT",
                "target_level": user_level,
                "reason_for_level": f"تصعيد SLA مسجل للمستوى ({user_level}): تجاوز الاستحقاق بـ {overdue_days} يوم",
                "title": (
                    f"معاملة متأخرة مصنفة ({subj.internal_number})"
                    if is_ts
                    else f"{subj.internal_number} · {subj.title}"
                ),
                "message": (
                    "توجد معاملة ذات درجة سرية خاصة متأخرة ومصعّدة عن الموعد المحدد."
                    if is_ts
                    else f"العهدة الحالية: {subj.current_owner} — متأخر منذ {overdue_days} يوم"
                ),
                "link_url": f"/subjects/{subj.id}/",
                "subject_id": subj.id,
                "is_top_secret": is_ts,
                "is_read": False,
                "is_live_escalation": False,
                "created_at": timezone.localtime(ref.escalated_at).strftime("%Y-%m-%d %H:%M"),
            }
        )

    escalated_tasks = (
        Task.objects.filter(escalated_at__isnull=False)
        .exclude(status__in=[Task.TaskStatus.COMPLETED, Task.TaskStatus.CANCELLED, Task.TaskStatus.REJECTED])
        .select_related("subject__confidentiality", "assigned_to", "assigned_by")
    )
    for task in escalated_tasks:
        subj = task.subject
        if task.subject_id in seen_overdue_subjects:
            continue
        if not PermissionService.can_view_subject(request.user, subj):
            continue
        is_relevant = (
            request.user.is_superuser
            or task.assigned_to_id == request.user.id
            or task.assigned_by_id == request.user.id
            or NotificationService.get_direct_manager(task.assigned_to) == request.user
        )
        if not is_relevant:
            continue

        is_ts = bool(subj.confidentiality.overrides_hierarchy)
        overdue_days = max(1, (today - task.due_date).days) if task.due_date and task.due_date < today else 0
        seen_overdue_subjects.add(task.subject_id)
        items.append(
            {
                "id": f"escalated-task-{task.id}",
                "category": "ESCALATION_OVERDUE",
                "raw_category": "ESCALATION_OVERDUE",
                "category_label": "تصعيد مهمة متأخرة",
                "priority": "URGENT",
                "target_level": user_level,
                "reason_for_level": f"تصعيد SLA مسجل للمستوى ({user_level}): تجاوز الاستحقاق بـ {overdue_days} يوم",
                "title": (
                    f"معاملة متأخرة مصنفة ({subj.internal_number})"
                    if is_ts
                    else f"{subj.internal_number} · {task.title}"
                ),
                "message": (
                    "توجد معاملة ذات درجة سرية خاصة متأخرة ومصعّدة عن الموعد المحدد."
                    if is_ts
                    else f"المكلَّف: {task.assigned_to} — متأخر منذ {overdue_days} يوم"
                ),
                "link_url": f"/subjects/{subj.id}/",
                "subject_id": subj.id,
                "is_top_secret": is_ts,
                "is_read": False,
                "is_live_escalation": False,
                "created_at": timezone.localtime(task.escalated_at).strftime("%Y-%m-%d %H:%M"),
            }
        )

    unread_count = sum(1 for item in items if not item["is_read"])
    return JsonResponse(
        {
            "user_level": user_level,
            "unread_count": unread_count,
            "notifications": items,
        }
    )


@login_required
@require_POST
def mark_read_api(request):
    """تعليم إشعار أو جميع الإشعارات كمقروء عبر AJAX."""
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = request.POST.dict()

    if payload.get("mark_all"):
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    elif payload.get("notification_id"):
        notif = Notification.objects.filter(id=payload.get("notification_id"), recipient=request.user).first()
        if notif:
            notif.is_read = True
            notif.save(update_fields=["is_read"])

    unread_db = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({"ok": True, "unread_db": unread_db})
