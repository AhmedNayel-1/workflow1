from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render
from accounts.models import User
from accounts.services import PermissionService
from core.models import SystemErrorLog
from decisions.models import Decision
from subjects.models import Annotation, Memo, Subject
from workflow.models import Referral, Task
from .models import ActivityLog, AuditLog


@login_required
def audit_log_view(request):
    """شاشة السجلات الموحدة: التعديلات، المشكلات والأخطاء، الأحداث، وتتبع مسار موضوع لمستخدم محدد."""
    if not (request.user.is_superuser or PermissionService.user_has_permission(request.user, "AUDIT_VIEW")):
        raise PermissionDenied("ليس لديك صلاحية الاطلاع على سجل التدقيق.")

    log_tab = request.GET.get("tab", "all").strip()
    q = request.GET.get("q", "").strip()
    trace_subject_id = request.GET.get("trace_subject_id", "").strip()
    trace_user_id = request.GET.get("trace_user_id", "").strip()

    audit_qs = AuditLog.objects.select_related("actor_user").all()
    if q:
        audit_qs = audit_qs.filter(
            Q(action__icontains=q)
            | Q(model_name__icontains=q)
            | Q(reason__icontains=q)
            | Q(actor_user__username__icontains=q)
            | Q(actor_user__first_name__icontains=q)
        )

    edit_actions = {
        "SUBJECT_UPDATED",
        "USER_CREATED",
        "USER_DELETED",
        "USER_DEACTIVATED_PROTECTED",
        "ASSIGN_ROLE",
        "REMOVE_ROLE",
        "TOGGLE_USER_ACTIVE",
        "UPDATE_ROLE_FLAG",
        "CREATE_DELEGATION",
        "REVOKE_DELEGATION",
        "COMPANY_CREATED",
        "DB_ADMIN_ADD_TX_TYPE",
        "DB_ADMIN_DELETE_ROW",
    }

    if log_tab == "edits":
        logs = list(audit_qs.filter(Q(action__in=edit_actions) | Q(action__icontains="UPDATE") | Q(action__icontains="CREATE") | Q(action__icontains="DELETE"))[:200])
    elif log_tab == "errors":
        logs = list(audit_qs.filter(outcome__in=["DENIED", "ERROR"])[:200])
    else:
        logs = list(audit_qs[:200])

    error_logs_qs = SystemErrorLog.objects.all()
    if q:
        error_logs_qs = error_logs_qs.filter(Q(component__icontains=q) | Q(error_message__icontains=q) | Q(operation__icontains=q))
    error_logs = list(error_logs_qs[:100])
    denied_audit_logs = list(audit_qs.filter(outcome__in=["DENIED", "ERROR"])[:100])

    activity_qs = ActivityLog.objects.select_related("subject", "actor_user", "acting_on_behalf_of").all()
    if q:
        activity_qs = activity_qs.filter(
            Q(action_type__icontains=q)
            | Q(description__icontains=q)
            | Q(subject__internal_number__icontains=q)
            | Q(subject__title__icontains=q)
        )
    activity_events = list(activity_qs.order_by("-created_at")[:150])

    # تتبع مسار موضوع معين لمستخدم معين (Subject-by-User Path Tracer)
    all_subjects = list(Subject.objects.select_related("sector", "confidentiality").order_by("-id")[:200])
    all_users = list(User.objects.select_related("employee__current_unit").order_by("id"))

    selected_subject = Subject.objects.filter(id=int(trace_subject_id)).first() if trace_subject_id.isdigit() else None
    selected_user = User.objects.filter(id=int(trace_user_id)).first() if trace_user_id.isdigit() else None
    trace_timeline = []

    if selected_subject is not None:
        uid = selected_user.id if selected_user is not None else None

        if uid is None or selected_subject.created_by_id == uid:
            trace_timeline.append({
                "timestamp": selected_subject.created_at,
                "kind": "SUBJECT",
                "kind_label": "إنشاء الموضوع",
                "actor": str(selected_subject.created_by),
                "summary": f"إنشاء الموضوع {selected_subject.internal_number}: {selected_subject.title}",
                "outcome": "SUCCESS",
            })

        for act in ActivityLog.objects.filter(subject=selected_subject).select_related("actor_user", "acting_on_behalf_of"):
            if uid is None or act.actor_user_id == uid or act.acting_on_behalf_of_id == uid:
                trace_timeline.append({
                    "timestamp": act.created_at,
                    "kind": "EVENT",
                    "kind_label": act.action_type,
                    "actor": str(act.actor_user or "النظام"),
                    "summary": act.description,
                    "outcome": "SUCCESS",
                })

        for ref in Referral.objects.filter(subject=selected_subject).select_related("referred_by").prefetch_related("recipients__target_user", "recipients__received_by"):
            recs = list(ref.recipients.all())
            is_sender = (uid == ref.referred_by_id)
            is_rec = any(r.target_user_id == uid or r.received_by_id == uid for r in recs)
            if uid is None or is_sender or is_rec:
                targets_str = "، ".join(str(r.target_user or r.target_unit) for r in recs) or "—"
                trace_timeline.append({
                    "timestamp": ref.created_at,
                    "kind": "REFERRAL",
                    "kind_label": f"إحالة ({ref.get_purpose_display()})",
                    "actor": str(ref.referred_by),
                    "summary": f"من {ref.referred_by} ← إلى {targets_str}" + (f" · {ref.notes}" if ref.notes else ""),
                    "outcome": "SUCCESS",
                })
            for r in recs:
                if r.received_at and (uid is None or r.received_by_id == uid or r.target_user_id == uid):
                    trace_timeline.append({
                        "timestamp": r.received_at,
                        "kind": "REFERRAL_ACK",
                        "kind_label": "استلام إحالة",
                        "actor": str(r.received_by or r.target_user or "—"),
                        "summary": f"تأكيد الاستلام ({r.get_status_display()}) على إحالة من {ref.referred_by}",
                        "outcome": "SUCCESS",
                    })

        for memo in Memo.objects.filter(subject=selected_subject).select_related("author", "approved_by"):
            if uid is None or memo.author_id == uid or memo.approved_by_id == uid:
                trace_timeline.append({
                    "timestamp": memo.created_at,
                    "kind": "MEMO",
                    "kind_label": "مذكرة عرض",
                    "actor": str(memo.author),
                    "summary": f"مذكرة {memo.memo_number}: {memo.title} (حالة: {memo.get_status_display()})",
                    "outcome": "SUCCESS",
                })

        for ann in Annotation.objects.filter(subject=selected_subject).select_related("author"):
            if uid is None or ann.author_id == uid:
                trace_timeline.append({
                    "timestamp": ann.created_at,
                    "kind": "ANNOTATION",
                    "kind_label": "تأشيرة إدارية",
                    "actor": str(ann.author),
                    "summary": ann.annotation_text,
                    "outcome": "SUCCESS",
                })

        for task in Task.objects.filter(subject=selected_subject).select_related("assigned_to", "assigned_by"):
            if uid is None or task.assigned_to_id == uid or task.assigned_by_id == uid:
                trace_timeline.append({
                    "timestamp": task.assigned_at,
                    "kind": "TASK",
                    "kind_label": "مهمة تنفيذية",
                    "actor": str(task.assigned_by),
                    "summary": f"{task.title} ← المكلف: {task.assigned_to} ({task.get_status_display()})",
                    "outcome": "SUCCESS",
                })

        for dec in Decision.objects.filter(subject=selected_subject).select_related("created_by", "approved_by"):
            if uid is None or dec.created_by_id == uid or dec.approved_by_id == uid:
                trace_timeline.append({
                    "timestamp": dec.created_at,
                    "kind": "DECISION",
                    "kind_label": "قرار إداري",
                    "actor": str(dec.created_by),
                    "summary": f"{dec.decision_number}: {dec.title} ({dec.get_status_display()})",
                    "outcome": "SUCCESS",
                })

        aud_filter = Q(model_name="Subject", object_id=selected_subject.id)
        if uid is not None:
            aud_filter &= Q(actor_user_id=uid)
        for aud in AuditLog.objects.filter(aud_filter).select_related("actor_user"):
            trace_timeline.append({
                "timestamp": aud.created_at,
                "kind": "AUDIT",
                "kind_label": aud.action,
                "actor": str(aud.actor_user or "النظام"),
                "summary": aud.reason or f"سجل تدقيق أمني ({aud.outcome})",
                "outcome": aud.outcome,
            })

        trace_timeline.sort(key=lambda item: item["timestamp"])

    return render(
        request,
        "audit/audit_log.html",
        {
            "log_tab": log_tab,
            "q": q,
            "logs": logs,
            "error_logs": error_logs,
            "denied_audit_logs": denied_audit_logs,
            "activity_events": activity_events,
            "all_subjects": all_subjects,
            "all_users": all_users,
            "selected_subject": selected_subject,
            "selected_user": selected_user,
            "trace_subject_id": trace_subject_id,
            "trace_user_id": trace_user_id,
            "trace_timeline": trace_timeline,
        },
    )
