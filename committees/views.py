from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from accounts.services import PermissionService
from audit.services import AuditService
from subjects.models import Subject
from .models import Committee, CommitteeAgendaItem, CommitteeMeeting


def _can_access_committee(user, committee) -> bool:
    if getattr(user, "is_superuser", False) or PermissionService.is_org_wide_manager(user):
        return True
    if committee.chair_id == user.id or committee.members.filter(id=user.id).exists():
        return True
    boundaries = PermissionService.get_user_scope_boundaries(user)
    return committee.sector_id in boundaries["allowed_sector_ids"]


@login_required
def committee_list(request):
    """عرض اللجان واجتماعاتها مع عزل القطاعات وإمكانية إنشاء جلسة للمصرح لهم."""
    if request.method == "POST":
        committee = get_object_or_404(Committee, id=request.POST.get("committee_id"))
        if not PermissionService.user_has_permission(request.user, "COMMITTEE_MANAGE", sector=committee.sector):
            raise PermissionDenied("ليس لديك صلاحية إدارة جلسات لجان هذا القطاع.")
        meeting = CommitteeMeeting.objects.create(
            committee=committee,
            meeting_number=request.POST.get("meeting_number", "").strip(),
            meeting_date=request.POST.get("meeting_date"),
            location=request.POST.get("location", "").strip(),
            minutes_summary=request.POST.get("minutes_summary", "").strip(),
            status=CommitteeMeeting.MeetingStatus.CONVENED,
            created_by=request.user,
        )
        messages.success(request, f"تم تسجيل اجتماع {committee.name} رقم {meeting.meeting_number}.")
        return redirect("committees:meeting_detail", meeting_id=meeting.id)

    all_committees = Committee.objects.select_related("sector", "chair").prefetch_related("meetings", "members").all()
    committees = [c for c in all_committees if _can_access_committee(request.user, c)]
    can_manage = PermissionService.user_has_permission(
        request.user, "COMMITTEE_MANAGE", sector=request.user.current_sector
    )
    # فهرس الموضوعات المرتبطة بكل لجنة (رابط منظَّم اختياري على قرار اللجنة الوارد)، مفلتر بصلاحية رؤية الموضوع
    from subjects.models import SubjectSuspension
    linked = {}
    for sp in SubjectSuspension.objects.filter(committee__in=committees).select_related("subject", "subject__confidentiality").order_by("-suspended_at"):
        if PermissionService.can_view_subject(request.user, sp.subject):
            linked.setdefault(sp.committee_id, []).append(sp)
    for c in committees:
        c.linked_topics = linked.get(c.id, [])
    return render(
        request,
        "committees/committee_list.html",
        {"committees": committees, "can_manage": can_manage},
    )


@login_required
def meeting_detail(request, meeting_id: int):
    """إدارة بنود الاجتماع وتسجيل قرارات اللجنة وربطها بالموضوعات مع عزل القطاعات."""
    meeting = get_object_or_404(
        CommitteeMeeting.objects.select_related("committee__sector", "created_by"), id=meeting_id
    )
    if not _can_access_committee(request.user, meeting.committee):
        raise PermissionDenied("غير مصرح لك بالاطلاع على اجتماعات لجنة خارج قطاعك.")

    if request.method == "POST":
        subject = get_object_or_404(Subject, id=request.POST.get("subject_id"))
        if not PermissionService.can_view_subject(request.user, subject):
            raise PermissionDenied("غير مصرح لك بالوصول لهذا الموضوع.")
        if not PermissionService.user_has_permission(
            request.user,
            "COMMITTEE_MANAGE",
            sector=meeting.committee.sector,
            confidentiality_rank=subject.confidentiality.rank,
            subject=subject,
        ):
            raise PermissionDenied("ليس لديك صلاحية تسجيل قرارات اللجان لهذا الموضوع/القطاع.")

        res_type = request.POST.get("resolution_type", CommitteeAgendaItem.ResolutionType.APPROVED)
        res_text = request.POST.get("resolution_text", "").strip()
        rec_text = request.POST.get("recommendation", "").strip()
        CommitteeAgendaItem.objects.create(
            meeting=meeting,
            subject=subject,
            recommendation=rec_text,
            resolution_type=res_type,
            resolution_text=res_text,
            recorded_by=request.user,
        )
        AuditService.record_activity(
            subject=subject,
            action_type="COMMITTEE_RESOLUTION",
            actor_user=request.user,
            description=f"نتيجة العرض على ({meeting.committee.name} - جلسة {meeting.meeting_number}): {res_text}",
        )
        messages.success(request, "تم تسجيل قرار اللجنة وربطه بالموضوع.")
        return redirect("committees:meeting_detail", meeting_id=meeting.id)

    raw_items = meeting.agenda_items.select_related("subject__confidentiality", "memo", "recorded_by").all()
    visible_items = [
        item for item in raw_items if PermissionService.can_view_subject(request.user, item.subject)
    ]
    visible_subjects = PermissionService.filter_visible_subjects(Subject.objects.all(), request.user)
    return render(
        request,
        "committees/meeting_detail.html",
        {
            "meeting": meeting,
            "items": visible_items,
            "visible_subjects": visible_subjects,
            "resolution_choices": CommitteeAgendaItem.ResolutionType.choices,
            "can_manage": PermissionService.user_has_permission(
                request.user, "COMMITTEE_MANAGE", sector=meeting.committee.sector
            ),
        },
    )


@login_required
def minutes_print(request, meeting_id: int):
    """قالب طباعة رسمي لمحضر اجتماع اللجنة."""
    meeting = get_object_or_404(CommitteeMeeting.objects.select_related("committee__chair"), id=meeting_id)
    if not _can_access_committee(request.user, meeting.committee):
        raise PermissionDenied("غير مصرح لك بطباعة محضر لجنة خارج قطاعك.")
    visible_items = [
        item
        for item in meeting.agenda_items.select_related("subject__confidentiality")
        if PermissionService.can_view_subject(request.user, item.subject)
    ]
    return render(request, "committees/minutes_print.html", {"meeting": meeting, "items": visible_items})
