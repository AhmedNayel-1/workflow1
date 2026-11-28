import uuid
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from core.pagination import page_size
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from accounts.models import User
from accounts.services import PermissionService
from audit.services import AuditService
from core.models import PriorityLevel
from notifications.models import Notification
from notifications.services import NotificationService
from organization.models import OrgUnit
from subjects.models import Subject
from .models import Referral, ReferralRecipient, Task, WorkflowTemplate, WorkflowTemplateVersion
from .services import WorkflowEngineService, apply_template


@login_required
def referral_inbox(request):
    """صندوق الإحالات الواردة والصادرة للمستخدم ووحدته مع احترام السرية."""
    unit = request.user.current_unit
    incoming_q = Q(target_user=request.user)
    if unit:
        incoming_q |= Q(target_unit=unit, target_user__isnull=True)

    raw_incoming = ReferralRecipient.objects.filter(incoming_q).select_related(
        "referral__subject__confidentiality",
        "referral__referred_by",
        "target_user",
        "target_unit",
    )
    incoming = [
        item
        for item in raw_incoming
        if PermissionService.can_view_subject(request.user, item.referral.subject)
    ]
    outgoing = list(
        Referral.objects.filter(referred_by=request.user)
        .select_related("subject")
        .prefetch_related("recipients__target_user", "recipients__target_unit")
    )
    for ref in outgoing:
        recs = list(ref.recipients.all())
        ref.can_withdraw = (
            not ref.is_completed
            and not ref.is_withdrawn
            and not any(
                r.received_at is not None
                or r.status
                in (
                    ReferralRecipient.RecipientStatus.RECEIVED,
                    ReferralRecipient.RecipientStatus.RESPONDED,
                    ReferralRecipient.RecipientStatus.VIEWED_ONLY,
                    ReferralRecipient.RecipientStatus.RETURNED,
                )
                for r in recs
            )
        )

    reassign_candidates = User.objects.filter(is_active=True).order_by("first_name", "username")
    if not request.user.is_superuser and not PermissionService.is_org_wide_manager(request.user):
        if request.user.current_sector:
            reassign_candidates = reassign_candidates.filter(
                employee__current_unit__sector=request.user.current_sector
            )

    return render(
        request,
        "workflow/referral_inbox.html",
        {
            "incoming": incoming,
            "outgoing": outgoing,
            "today_date": timezone.localdate(),
            "reassign_candidates": reassign_candidates,
        },
    )


@login_required
def referral_create(request, subject_id: int):
    """إنشاء إحالة مرنة (مباشرة / متتابعة / متوازية / للعلم فقط) وفق التسلسل الهرمي."""
    subject = get_object_or_404(Subject, id=subject_id)
    if not PermissionService.can_view_subject(request.user, subject):
        raise PermissionDenied("غير مصرح لك بالوصول للموضوع.")
    if not PermissionService.user_has_permission(
        request.user,
        "REFERRAL_CREATE",
        sector=subject.sector,
        confidentiality_rank=subject.confidentiality.rank,
        subject=subject,
    ):
        raise PermissionDenied("ليس لديك صلاحية إحالة الموضوع.")
    if not PermissionService.can_act_on_subject(request.user, subject):
        raise PermissionDenied("هذا الموضوع للاطلاع فقط في مستواك الحالي؛ ولا يمكنك تعديله أو إنشاء إحالات عليه.")

    allowed_users = PermissionService.get_allowed_referral_targets(request.user, subject)
    allowed_units = PermissionService.get_allowed_referral_units(request.user, subject)

    if request.method == "POST":
        try:
            user_ids = request.POST.getlist("target_user_ids")
            unit_ids = request.POST.getlist("target_unit_ids")
            target_users = list(User.objects.filter(id__in=user_ids, is_active=True))
            target_units = list(OrgUnit.objects.filter(id__in=unit_ids, is_active=True))
            from datetime import date as _d
            _due = request.POST.get("due_date") or ""
            if _due:
                try:
                    if _d.fromisoformat(_due) < timezone.localdate():
                        raise ValidationError("لا يمكن اختيار موعد نهائي في يوم سابق.")
                except ValueError:
                    raise ValidationError("الموعد النهائي غير صحيح.")
            mode = request.POST.get("routing_mode", "TOGETHER")
            if mode == "TOGETHER":
                mode = Referral.RoutingMode.PARALLEL if (len(target_users) + len(target_units)) > 1 else Referral.RoutingMode.DIRECT
            req_unit_id = request.POST.get("required_unit_id") or None
            req_unit = OrgUnit.objects.filter(id=req_unit_id).first() if req_unit_id else None

            WorkflowEngineService.create_referral(
                subject=subject,
                referred_by=request.user,
                routing_mode=mode,
                purpose=request.POST.get("purpose", Referral.Purpose.FOR_EXECUTION),
                notes=request.POST.get("notes", "").strip(),
                target_users=target_users,
                target_units=target_units,
                parallel_completion_rule=request.POST.get(
                    "parallel_completion_rule", Referral.ParallelCompletionRule.ALL
                ),
                required_unit=req_unit,
                due_date=request.POST.get("due_date") or None,
                idempotency_key=request.POST.get("idempotency_key") or None,
            )
            messages.success(request, "تم تسجيل الإحالة بنجاح.")
            nxt = request.POST.get("next") or ""
            if nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect("subjects:subject_detail", subject_id=subject.id)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))

    roles = PermissionService.get_effective_role_codes(request.user, sector=subject.sector)
    delegation = PermissionService.get_acting_delegation(request.user, "REFERRAL_CREATE", subject=subject)
    if delegation and ("SECRETARIAT" in roles or not roles):
        roles = PermissionService.get_effective_role_codes(delegation.delegator, sector=subject.sector)

    if "GENERAL_MANAGER" in roles:
        routing_hint = "التوجيه المتاح للمدير العام (أو سكرتاريته): يوجَّه الموضوع حصراً إلى رئيس القسم أو مشرف القسم الأدنى والمختص بالموضوع."
    elif "SUPERVISOR" in roles:
        routing_hint = "التوزيع المتاح لرئيس/مشرف القسم (أو سكرتارية القسم): يوزَّع الموضوع حصراً على الموظف المختص التابع لنفس القسم."
    elif "SECTOR_HEAD" in roles:
        routing_hint = "التوجيه المتاح لرئيس القطاع (أو سكرتاريته): يوجَّه الموضوع إلى المدير العام المختص (ولا يجوز للادنى تعديل إحالات رئيس القطاع)."
    else:
        routing_hint = "اختر المستلم المعتمد وفق صلاحيات التوجيه في المنظومة."

    return render(
        request,
        "workflow/_referral_fields.html" if request.GET.get("partial") == "1" else "workflow/referral_form.html",
        {
            "today": timezone.localdate().isoformat(),
            "subject": subject,
            "users": allowed_users,
            "org_units": allowed_units,
            "routing_choices": Referral.RoutingMode.choices,
            "purpose_choices": Referral.Purpose.choices,
            "parallel_rules": Referral.ParallelCompletionRule.choices,
            "idempotency_key": str(uuid.uuid4()),
            "routing_hint": routing_hint,
        },
    )


@login_required
def referral_respond(request, recipient_id: int):
    """استلام أو الرد على إحالة."""
    recipient_item = get_object_or_404(
        ReferralRecipient.objects.select_related("referral__subject"), id=recipient_id
    )
    if not PermissionService.can_view_subject(request.user, recipient_item.referral.subject):
        raise PermissionDenied("غير مصرح لك بالتعامل مع هذه الإحالة.")

    is_target = recipient_item.target_user_id == request.user.id or (
        recipient_item.target_user_id is None
        and request.user.current_unit
        and recipient_item.target_unit_id == request.user.current_unit.id
    )
    if not is_target:
        delegation = PermissionService.get_acting_delegation(
            request.user, "REFERRAL_CREATE", subject=recipient_item.referral.subject
        )
        is_target = bool(
            delegation and recipient_item.target_user_id == delegation.delegator_id
        )
    if not is_target and not request.user.is_superuser:
        raise PermissionDenied("الاستلام أو الرد متاح للمحال إليه الفعلي فقط؛ الإحالة للاطلاع فقط لغيره.")

    if request.method == "POST":
        action = request.POST.get("action", "complete")
        try:
            if action == "reject_return":
                WorkflowEngineService.reject_or_return_recipient(
                    recipient_item=recipient_item,
                    user=request.user,
                    reason=request.POST.get("reason") or request.POST.get("response_notes", ""),
                )
                messages.warning(request, "تم رفض/إرجاع الإحالة إلى المحيل بنجاح.")
            else:
                WorkflowEngineService.acknowledge_or_complete_recipient(
                    recipient_item=recipient_item,
                    user=request.user,
                    response_notes=request.POST.get("response_notes", "").strip(),
                    complete=(action not in ("receive_only", "acknowledge")),
                    force_complete_parallel=(request.POST.get("force_complete_parallel") == "on"),
                )
                messages.success(request, "تم تحديث حالة الإحالة بنجاح.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("subjects:subject_detail", subject_id=recipient_item.referral.subject_id)


@login_required
def referral_reject(request, recipient_id: int):
    """رفض أو إرجاع الإحالة من المستلم إلى المحيل مع سبب إجباري."""
    recipient_item = get_object_or_404(
        ReferralRecipient.objects.select_related("referral__subject", "referral__referred_by"),
        id=recipient_id,
    )
    if not PermissionService.can_view_subject(request.user, recipient_item.referral.subject):
        raise PermissionDenied("غير مصرح لك بالتعامل مع هذه الإحالة.")

    is_target = recipient_item.target_user_id == request.user.id or (
        recipient_item.target_user_id is None
        and request.user.current_unit
        and recipient_item.target_unit_id == request.user.current_unit.id
    )
    if not is_target:
        delegation = PermissionService.get_acting_delegation(
            request.user, "REFERRAL_CREATE", subject=recipient_item.referral.subject
        )
        is_target = bool(delegation and recipient_item.target_user_id == delegation.delegator_id)
    if not is_target and not request.user.is_superuser:
        raise PermissionDenied("رفض أو إرجاع الإحالة متاح للمحال إليه الفعلي فقط.")

    if request.method == "POST":
        try:
            WorkflowEngineService.reject_or_return_recipient(
                recipient_item=recipient_item,
                user=request.user,
                reason=request.POST.get("reason", ""),
            )
            messages.warning(request, "تم إرجاع الإحالة إلى المحيل بنجاح.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("subjects:subject_detail", subject_id=recipient_item.referral.subject_id)


@login_required
def referral_withdraw(request, referral_id: int):
    """سحب الإحالة من قِبل المحيل طالما لم يتم استلامها."""
    referral = get_object_or_404(
        Referral.objects.select_related("subject", "referred_by"),
        id=referral_id,
    )
    if not PermissionService.can_view_subject(request.user, referral.subject):
        raise PermissionDenied("غير مصرح لك بالوصول إلى هذه الإحالة.")

    if request.method == "POST":
        try:
            WorkflowEngineService.withdraw_referral(
                referral=referral,
                user=request.user,
                reason=request.POST.get("reason", ""),
            )
            messages.info(request, "تم سحب الإحالة بنجاح وإعادة العهدة للمحيل.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("subjects:subject_detail", subject_id=referral.subject_id)


@login_required
def referral_reassign(request, recipient_id: int):
    """إعادة إسناد مستلم معلق لمستخدم آخر."""
    recipient_item = get_object_or_404(
        ReferralRecipient.objects.select_related("referral__subject", "referral__referred_by"),
        id=recipient_id,
    )
    if not PermissionService.can_view_subject(request.user, recipient_item.referral.subject):
        raise PermissionDenied("غير مصرح لك بالوصول إلى هذه الإحالة.")

    if request.method == "POST":
        new_user_id = request.POST.get("new_user_id")
        new_user = User.objects.filter(id=new_user_id, is_active=True).first() if new_user_id else None
        if new_user is None:
            messages.error(request, "يرجى اختيار مستخدم نشط لإعادة الإسناد.")
        else:
            subject = recipient_item.referral.subject
            if not request.user.is_superuser and not PermissionService.is_org_wide_manager(request.user):
                if new_user.current_sector and new_user.current_sector.id != subject.sector_id:
                    raise PermissionDenied("لا يمكن إعادة إسناد الإحالة لمستخدم خارج قطاع الموضوع.")
            try:
                WorkflowEngineService.reassign_recipient(
                    recipient_item=recipient_item,
                    new_user=new_user,
                    user=request.user,
                    reason=request.POST.get("reason", ""),
                )
                messages.success(request, f"تمت إعادة إسناد الإحالة إلى {new_user} بنجاح.")
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("subjects:subject_detail", subject_id=recipient_item.referral.subject_id)


@login_required
def apply_workflow_template(request, subject_id: int):
    """تطبيق إصدار قالب مسار العمل على الموضوع من صفحة التفاصيل."""
    subject = get_object_or_404(Subject, id=subject_id)
    if not PermissionService.can_view_subject(request.user, subject):
        raise PermissionDenied("غير مصرح لك بالوصول للموضوع.")
    if not PermissionService.user_has_permission(
        request.user,
        "REFERRAL_CREATE",
        sector=subject.sector,
        confidentiality_rank=subject.confidentiality.rank,
        subject=subject,
    ):
        raise PermissionDenied("ليس لديك صلاحية تطبيق قالب إحالات على الموضوع.")
    if not PermissionService.can_act_on_subject(request.user, subject):
        raise PermissionDenied("هذا الموضوع للاطلاع فقط في مستواك الحالي.")

    if request.method == "POST":
        version_id = request.POST.get("template_version_id")
        template_version = (
            WorkflowTemplateVersion.objects.filter(id=version_id, is_active=True, template__is_active=True).first()
            if version_id
            else None
        )
        try:
            created_refs = apply_template(subject, template_version, request.user)
            messages.success(request, f"تم تطبيق قالب مسار العمل وإنشاء {len(created_refs)} إحالة بنجاح.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    return redirect("subjects:subject_detail", subject_id=subject.id)


@login_required
def task_list(request):
    """لوحة المهام والتكليفات الخاصة بالمستخدم مع التمييز عن حالة الموضوع واحترام السرية."""
    if request.user.is_superuser:
        tasks = Task.objects.select_related("subject__confidentiality", "assigned_to", "assigned_by", "priority").all()
    else:
        delegations = PermissionService.get_active_delegations_for_delegate(request.user)
        delegator_ids = [d.delegator_id for d in delegations]
        tasks = Task.objects.filter(
            Q(assigned_to=request.user) | Q(assigned_by=request.user) | Q(assigned_to_id__in=delegator_ids)
        ).select_related("subject__confidentiality", "assigned_to", "assigned_by", "priority")
    visible_tasks = [
        t for t in tasks if PermissionService.can_view_subject(request.user, t.subject)
    ]
    paginator = Paginator(visible_tasks, page_size(request))
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "workflow/task_list.html",
        {
            "tasks": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "total_count": paginator.count,
            "status_choices": Task.TaskStatus.choices,
            "today": timezone.localdate(),
        },
    )


@login_required
def task_create(request, subject_id: int):
    """إنشاء مهمة تنفيذية مستقلة على الموضوع بعد التحقق من العهدة وعزل القطاع."""
    subject = get_object_or_404(Subject, id=subject_id)
    if not PermissionService.can_view_subject(request.user, subject):
        raise PermissionDenied("غير مصرح لك بالوصول للموضوع.")
    if not PermissionService.user_has_permission(
        request.user,
        "TASK_CREATE",
        sector=subject.sector,
        confidentiality_rank=subject.confidentiality.rank,
        subject=subject,
    ):
        raise PermissionDenied("ليس لديك صلاحية إنشاء المهام.")
    if not PermissionService.can_act_on_subject(request.user, subject):
        raise PermissionDenied("لا يمكنك إنشاء مهمة على موضوع ليس في عهدتك التنفيذية.")

    if request.method == "POST":
        assigned_to = get_object_or_404(User, id=request.POST.get("assigned_to_id"), is_active=True)
        if not request.user.is_superuser and not PermissionService.is_org_wide_manager(request.user):
            if assigned_to.current_sector and assigned_to.current_sector.id != subject.sector_id:
                raise PermissionDenied("لا يمكن تكليف موظف من خارج قطاع الموضوع.")
        prio_id = request.POST.get("priority_id")
        prio = PriorityLevel.objects.filter(id=prio_id).first() if prio_id else subject.priority
        WorkflowEngineService.create_task(
            subject=subject,
            title=request.POST.get("title", "").strip(),
            description=request.POST.get("description", "").strip(),
            assigned_to=assigned_to,
            assigned_by=request.user,
            due_date=request.POST.get("due_date") or None,
            priority=prio,
        )
        messages.success(request, "تم إنشاء المهمة وتكليف الموظف بنجاح.")
    return redirect("subjects:subject_detail", subject_id=subject.id)


@login_required
def task_update_status(request, task_id: int):
    """تحديث حالة المهمة متاح حصراً للمكلف بالمهمة أو منشئها (أو المفوض/Superuser)."""
    task = get_object_or_404(Task.objects.select_related("subject", "assigned_by", "assigned_to"), id=task_id)
    if not PermissionService.can_view_subject(request.user, task.subject):
        raise PermissionDenied("غير مصرح لك بتعديل هذه المهمة.")

    is_task_actor = (
        request.user.is_superuser
        or task.assigned_to_id == request.user.id
        or task.assigned_by_id == request.user.id
    )
    if not is_task_actor:
        delegation = PermissionService.get_acting_delegation(request.user, "TASK_CREATE", subject=task.subject)
        is_task_actor = bool(
            delegation and delegation.delegator_id in (task.assigned_to_id, task.assigned_by_id)
        )
    if not is_task_actor:
        raise PermissionDenied("تحديث حالة المهمة مقتصر على الموظف المكلف بها أو منشئ التكليف فقط.")

    if request.method == "POST":
        new_status = request.POST.get("status", task.status)
        valid_statuses = {choice[0] for choice in Task.TaskStatus.choices}
        if new_status not in valid_statuses:
            messages.error(request, "حالة المهمة المختارة غير صالحة.")
            return redirect(request.POST.get("next") or "workflow:task_list")
        outcome = request.POST.get("outcome", task.outcome)
        task.status = new_status
        task.outcome = outcome
        if new_status == Task.TaskStatus.COMPLETED:
            task.completed_at = timezone.now()
            task.completed_by = request.user
        task.save()

        AuditService.record_activity(
            subject=task.subject,
            action_type="TASK_UPDATED",
            actor_user=request.user,
            description=f"تحديث حالة المهمة ({task.title}) إلى: {task.get_status_display()}",
        )
        if new_status == Task.TaskStatus.COMPLETED:
            NotificationService.notify(
                recipient=task.assigned_by,
                subject=task.subject,
                category=Notification.Category.TASK,
                title=f"اكتمال مهمة: {task.title}",
                message=f"أنهى {request.user} المهمة المكلف بها على الموضوع {task.subject.internal_number}.",
                link_url=f"/subjects/{task.subject_id}/",
            )
        messages.success(request, "تم تحديث حالة المهمة.")
    return redirect(request.POST.get("next") or "workflow:task_list")


@login_required
def workflow_templates_list(request):
    """عرض قوالب مسارات العمل الافتراضية وإصداراتها."""
    templates = WorkflowTemplate.objects.select_related("transaction_type", "sector").prefetch_related(
        "versions__steps__suggested_unit"
    )
    return render(request, "workflow/templates_list.html", {"templates": templates})
