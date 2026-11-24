from django.core.paginator import Paginator
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from accounts.models import User
from accounts.services import PermissionService
from audit.services import AuditService
from committees.models import CommitteeAgendaItem
from core.models import (
    ConfidentialityLevel,
    DocumentType,
    MemoRecipientRef,
    MemoTypeRef,
    PriorityLevel,
    SuspensionReason,
    SystemSequence,
    TransactionType,
)
from core.pdf_utils import build_institutional_pdf_bytes, pdf_http_response
from decisions.models import Decision
from documents.models import Document, SubjectDocumentLink
from documents.services import DocumentService
from notifications.models import Notification
from notifications.services import NotificationService
from organization.models import OrgUnit, Sector
from workflow.models import Referral, ReferralRecipient, Task, WorkflowTemplateVersion
from workflow.services import WorkflowEngineService, apply_template
from .models import Annotation, Memo, Subject, SubjectAccessGrant, SubjectSuspension
from .guidance import build_subject_guidance
from .services import OptimisticLockError, SubjectService


@login_required
def subject_list(request):
    """قائمة الموضوعات المصفاة بصلاحية المستخدم ودرجة السرية مع دعم التصفح بالصفحات."""
    qs = Subject.objects.select_related(
        "transaction_type", "sector", "org_unit", "confidentiality", "priority", "current_owner"
    )
    status_filter = request.GET.get("status")
    sector_filter = request.GET.get("sector")
    if status_filter:
        qs = qs.filter(status=status_filter)
    if sector_filter:
        qs = qs.filter(sector_id=sector_filter)

    visible_subjects = PermissionService.filter_visible_subjects(qs, request.user)
    paginator = Paginator(visible_subjects, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    sectors = Sector.objects.filter(is_active=True)
    can_create = PermissionService.user_has_permission(request.user, "SUBJECT_CREATE")

    return render(
        request,
        "subjects/subject_list.html",
        {
            "subjects": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "total_count": paginator.count,
            "sectors": sectors,
            "status_choices": Subject.Status.choices,
            "status_filter": status_filter or "",
            "sector_filter": sector_filter or "",
            "can_create": can_create,
        },
    )


@login_required
def subject_create(request):
    """إنشاء موضوع جديد أو إرسال رسالة داخلية ثنائية الوضع."""
    if not PermissionService.user_has_permission(request.user, "SUBJECT_CREATE"):
        raise PermissionDenied("ليس لديك صلاحية إنشاء موضوع جديد.")

    if request.method == "POST":
        compose_mode = request.POST.get("compose_mode", "document").strip()
        title = request.POST.get("title", "").strip()
        if not title:
            messages.error(request, "عنوان الموضوع أو الرسالة مطلوب.")
            return redirect("subjects:subject_create")

        tx_id = request.POST.get("transaction_type_id")
        sector_id = request.POST.get("sector_id")
        org_unit_id = request.POST.get("org_unit_id")
        conf_id = request.POST.get("confidentiality_id")
        prio_id = request.POST.get("priority_id")

        if compose_mode == "message":
            emp_unit = getattr(getattr(request.user, "employee", None), "current_unit", None)
            tx_type = TransactionType.objects.filter(id=tx_id, is_active=True).first() if tx_id else TransactionType.objects.filter(is_active=True).first()
            org_unit = (OrgUnit.objects.filter(id=org_unit_id, is_active=True).first() if org_unit_id else emp_unit) or OrgUnit.objects.filter(is_active=True).first()
            sector = (Sector.objects.filter(id=sector_id, is_active=True).first() if sector_id else (org_unit.sector if org_unit else None)) or Sector.objects.filter(is_active=True).first()
            conf = ConfidentialityLevel.objects.filter(id=conf_id, is_active=True).first() if conf_id else ConfidentialityLevel.objects.order_by("rank").first()
            prio = PriorityLevel.objects.filter(id=prio_id, is_active=True).first() if prio_id else PriorityLevel.objects.order_by("rank").first()
        else:
            tx_type = get_object_or_404(TransactionType, id=tx_id)
            sector = get_object_or_404(Sector, id=sector_id)
            org_unit = get_object_or_404(OrgUnit, id=org_unit_id)
            conf = get_object_or_404(ConfidentialityLevel, id=conf_id)
            prio = get_object_or_404(PriorityLevel, id=prio_id)

        if not PermissionService.user_has_permission(
            request.user, "SUBJECT_CREATE", sector=sector, confidentiality_rank=conf.rank
        ):
            raise PermissionDenied("ليس لديك صلاحية إنشاء موضوع في هذا القطاع أو بهذا المستوى من السرية.")
        owner_id = request.POST.get("current_owner_id")
        owner = get_object_or_404(User, id=owner_id) if owner_id else request.user

        # في وضع الرسالة، تحديد أول مستلم من قائمة "إلى" كمالك حالي إذا لم يُختر مالك صريح
        to_user_ids = [int(x) for x in request.POST.getlist("to_user_ids") if str(x).isdigit()]
        cc_user_ids = [int(x) for x in request.POST.getlist("cc_user_ids") if str(x).isdigit()]
        bcc_user_ids = [int(x) for x in request.POST.getlist("bcc_user_ids") if str(x).isdigit()]
        to_unit_ids = [int(x) for x in request.POST.getlist("to_unit_ids") if str(x).isdigit()]

        if compose_mode == "message" and not owner_id and to_user_ids:
            first_to = User.objects.filter(id=to_user_ids[0], is_active=True).first()
            if first_to:
                owner = first_to

        subject = SubjectService.create_subject(
            title=title,
            description=request.POST.get("description", ""),
            transaction_type=tx_type,
            sector=sector,
            org_unit=org_unit,
            confidentiality=conf,
            priority=prio,
            created_by=request.user,
            current_owner=owner,
            applicant_name=request.POST.get("applicant_name", ""),
            external_source=request.POST.get("external_source", "") or ("مراسلة داخلية" if compose_mode == "message" else ""),
            keywords=request.POST.get("keywords", ""),
            status=request.POST.get("status", Subject.Status.INCOMING),
            due_date=request.POST.get("due_date") or None,
        )

        # رفع وربط المستندات المبدئية إن وُجدت أثناء الإنشاء
        uploaded_list = request.FILES.getlist("initial_attachment")
        if uploaded_list:
            doc_type_id = request.POST.get("initial_doc_type_id")
            chosen_doc_type = (
                DocumentType.objects.filter(id=doc_type_id, is_active=True).first()
                if doc_type_id
                else DocumentType.objects.filter(is_active=True).first()
            )
            if chosen_doc_type:
                try:
                    DocumentService.register_document(
                        title=request.POST.get("initial_doc_title", "").strip() or uploaded_list[0].name,
                        doc_type=chosen_doc_type,
                        confidentiality=conf,
                        created_by=request.user,
                        summary=subject.description or subject.title,
                        subject=subject,
                        uploaded_files=uploaded_list,
                    )
                except ValidationError as exc:
                    messages.warning(request, f"تم إنشاء الموضوع ولكن تعذر حفظ المرفق: {exc}")

        if compose_mode == "message":
            to_users = list(User.objects.filter(id__in=to_user_ids, is_active=True))
            to_units = list(OrgUnit.objects.filter(id__in=to_unit_ids, is_active=True))
            cc_users = list(User.objects.filter(id__in=cc_user_ids, is_active=True))
            bcc_users = list(User.objects.filter(id__in=bcc_user_ids, is_active=True))
            if to_users or to_units:
                try:
                    WorkflowEngineService.create_referral(
                        subject=subject,
                        referred_by=request.user,
                        routing_mode=Referral.RoutingMode.PARALLEL if (len(to_users) + len(to_units) > 1) else Referral.RoutingMode.DIRECT,
                        purpose=Referral.Purpose.FOR_EXECUTION,
                        notes=request.POST.get("description", "").strip() or title,
                        target_users=to_users or None,
                        target_units=to_units or None,
                        enforce_hierarchy=False,
                    )
                except ValidationError:
                    pass
            info_users = [u for u in (cc_users + bcc_users) if u not in to_users]
            if info_users:
                try:
                    WorkflowEngineService.create_referral(
                        subject=subject,
                        referred_by=request.user,
                        routing_mode=Referral.RoutingMode.PARALLEL,
                        purpose=Referral.Purpose.FOR_INFO,
                        notes="نسخة للاطلاع والعلم",
                        target_users=info_users,
                        enforce_hierarchy=False,
                    )
                except ValidationError:
                    pass
        else:
            # تسجيل توجيه رئيس القطاع المبدئي كإحالة مقفلة للاطلاع فقط إذا أُسند لمدير عام أو وُجد نص توجيه
            sector_directive = request.POST.get("sector_directive", "").strip()
            owner_roles = PermissionService.get_effective_role_codes(owner, sector=sector)
            if owner != request.user and (sector_directive or "GENERAL_MANAGER" in owner_roles):
                sector_head = (
                    User.objects.filter(
                        is_active=True,
                        role_assignments__is_active=True,
                        role_assignments__role__code="SECTOR_HEAD",
                        role_assignments__sector=sector,
                    ).first()
                    or request.user
                )
                try:
                    WorkflowEngineService.create_referral(
                        subject=subject,
                        referred_by=sector_head,
                        routing_mode=Referral.RoutingMode.DIRECT,
                        purpose=Referral.Purpose.FOR_EXECUTION,
                        notes=sector_directive or f"توجيه رئيس القطاع: يُحال إلى {owner} لاتخاذ اللازم وتوجيهه للقسم المختص.",
                        target_users=[owner],
                        enforce_hierarchy=False,
                    )
                except ValidationError:
                    pass

        # تطبيق قالب مسار العمل عند اختياره من نموذج الإنشاء
        tpl_version_id = request.POST.get("workflow_template_version_id")
        if tpl_version_id:
            tpl_version = WorkflowTemplateVersion.objects.filter(
                id=tpl_version_id, is_active=True, template__is_active=True
            ).first()
            if tpl_version:
                try:
                    apply_template(subject, tpl_version, request.user)
                except ValidationError as exc:
                    messages.warning(
                        request,
                        f"تم إنشاء الموضوع ولكن تعذر تطبيق قالب المسار: {'; '.join(exc.messages) if hasattr(exc, 'messages') else exc}",
                    )

        messages.success(request, f"تم {'إرسال الرسالة' if compose_mode == 'message' else 'إنشاء الموضوع'} بنجاح بالرقم الداخلي {subject.internal_number}.")
        return redirect("subjects:subject_detail", subject_id=subject.id)

    return render(
        request,
        "subjects/subject_form.html",
        {
            "transaction_types": TransactionType.objects.filter(is_active=True),
            "sectors": Sector.objects.filter(is_active=True),
            "org_units": OrgUnit.objects.filter(is_active=True).select_related("sector"),
            "confidentialities": ConfidentialityLevel.objects.filter(is_active=True),
            "priorities": PriorityLevel.objects.filter(is_active=True),
            "doc_types": DocumentType.objects.filter(is_active=True),
            "users": User.objects.filter(is_active=True),
            "template_versions": WorkflowTemplateVersion.objects.filter(
                is_active=True, template__is_active=True
            ).select_related("template", "template__transaction_type", "template__sector"),
        },
    )


@login_required
def subject_detail(request, subject_id: int):
    """
    صفحة تفاصيل الموضوع — سلسلة محادثة على نمط Gmail مع تجميع المرفقات حسب نوع المستند.
    """
    subject = get_object_or_404(
        Subject.objects.select_related(
            "transaction_type",
            "sector",
            "org_unit",
            "confidentiality",
            "priority",
            "current_owner",
            "created_by",
            "workflow_template_version__template",
        ),
        id=subject_id,
    )
    if not PermissionService.can_view_subject(request.user, subject):
        raise PermissionDenied("غير مصرح لك بالاطلاع على هذا الموضوع أو مستوى سريته.")

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action in {"update_meta", "add_memo", "suspend", "fulfill_suspension", "close_subject", "add_annotation", "upload_attachment", "apply_template"} and not PermissionService.can_act_on_subject(request.user, subject):
                raise PermissionDenied("هذا الموضوع للاطلاع فقط في مستواك الحالي؛ لا يمكنك تعديل إجراءاته أو إحالات رئيس القطاع.")

            if action == "upload_attachment":
                if not PermissionService.user_has_permission(
                    request.user, "DOCUMENT_CREATE", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject
                ):
                    raise PermissionDenied("ليس لديك صلاحية إرفاق مستندات.")
                uploaded_files = request.FILES.getlist("attachment_file")
                doc_type = (
                    DocumentType.objects.filter(id=request.POST.get("doc_type_id"), is_active=True).first()
                    or DocumentType.objects.filter(is_active=True).first()
                )
                doc_title = request.POST.get("doc_title", "").strip() or (uploaded_files[0].name if uploaded_files else "")
                if not doc_title:
                    raise ValidationError("عنوان المستند أو اختيار الملف مطلوب.")
                if doc_type:
                    doc = DocumentService.register_document(
                        title=doc_title,
                        doc_type=doc_type,
                        confidentiality=subject.confidentiality,
                        created_by=request.user,
                        summary=request.POST.get("doc_summary", "").strip() or subject.title,
                        subject=subject,
                        is_primary_subject=False,
                        relation_type=SubjectDocumentLink.RelationType.SUPPORTING,
                        uploaded_files=uploaded_files,
                    )
                    messages.success(request, f"تم رفع وإرفاق المستند ({doc.internal_number}) تحت تصنيف «{doc_type.name}» ({len(uploaded_files)} ملف).")

            elif action == "update_meta":
                if not PermissionService.user_has_permission(
                    request.user, "SUBJECT_EDIT", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject
                ):
                    raise PermissionDenied("ليس لديك صلاحية تعديل بيانات الموضوع.")
                expected_version = int(request.POST.get("version_lock", "0"))
                SubjectService.update_subject_with_lock(
                    subject.id,
                    expected_version,
                    request.user,
                    title=request.POST.get("title", subject.title).strip(),
                    description=request.POST.get("description", subject.description),
                    keywords=request.POST.get("keywords", subject.keywords),
                )
                messages.success(request, "تم تحديث بيانات الموضوع.")

            elif action == "add_memo":
                if not PermissionService.user_has_permission(
                    request.user, "MEMO_CREATE", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject
                ):
                    raise PermissionDenied("ليس لديك صلاحية إعداد مذكرة.")
                memo_num = SystemSequence.next_number("MEMO", "MEM")
                directed_sel = request.POST.get("directed_to_select", "").strip()
                directed_custom = request.POST.get("directed_to_custom", "").strip()
                directed_legacy = request.POST.get("directed_to", "").strip()
                if directed_sel == "__CUSTOM__":
                    final_directed_to = directed_custom or directed_legacy or "غير محدد"
                else:
                    final_directed_to = directed_sel or directed_legacy or "رئيس مجلس الإدارة"

                memo = Memo.objects.create(
                    subject=subject,
                    memo_number=memo_num,
                    memo_type=request.POST.get("memo_type", Memo.MemoType.PRESENTATION),
                    title=request.POST.get("memo_title", "").strip(),
                    directed_to=final_directed_to,
                    body=request.POST.get("memo_body", "").strip(),
                    status=request.POST.get("memo_status", Memo.MemoStatus.DRAFT),
                    author=request.user,
                )
                memo_file = request.FILES.get("memo_attachment")
                if memo_file is not None:
                    memo_doc_type = (
                        DocumentType.objects.filter(code="MEMO_DOC", is_active=True).first()
                        or DocumentType.objects.filter(is_active=True).first()
                    )
                    if memo_doc_type:
                        DocumentService.register_document(
                            title=f"مرفق المذكرة {memo.memo_number}: {memo.title}",
                            doc_type=memo_doc_type,
                            confidentiality=subject.confidentiality,
                            created_by=request.user,
                            summary=memo.body,
                            subject=subject,
                            is_primary_subject=False,
                            relation_type=SubjectDocumentLink.RelationType.SUPPORTING,
                            uploaded_file=memo_file,
                        )
                AuditService.record_activity(
                    subject=subject,
                    action_type="MEMO_CREATED",
                    actor_user=request.user,
                    description=f"تم إعداد {memo.get_memo_type_display()} رقم {memo.memo_number}: {memo.title}",
                )
                # إشعار ذكي لرئيس القطاع / مدير العام بمذكرة الرد الجديدة
                notify_targets = set()
                if subject.created_by_id and subject.created_by_id != request.user.id:
                    notify_targets.add(subject.created_by)
                if subject.current_owner_id and subject.current_owner_id != request.user.id:
                    notify_targets.add(subject.current_owner)
                for tgt in notify_targets:
                    NotificationService.notify(
                        recipient=tgt,
                        subject=subject,
                        category=Notification.Category.REPLY_MEMO,
                        priority=getattr(subject.priority, "code", "NORMAL"),
                        title=f"مذكرة جديدة ({memo.memo_number}) على {subject.internal_number}",
                        message=f"أعد {request.user} {memo.get_memo_type_display()} موجهة إلى: {final_directed_to}",
                        link_url=f"/subjects/{subject.id}/",
                    )
                messages.success(request, f"تم حفظ المذكرة رقم {memo.memo_number}.")

            elif action == "approve_memo":
                if not PermissionService.user_has_permission(
                    request.user, "APPROVAL_GRANT", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject
                ):
                    raise PermissionDenied("ليس لديك صلاحية اعتماد المذكرة.")
                memo = get_object_or_404(Memo, id=request.POST.get("memo_id"), subject=subject)
                memo.status = Memo.MemoStatus.APPROVED
                memo.approved_by = request.user
                memo.save(update_fields=["status", "approved_by", "updated_at"])
                AuditService.record_activity(
                    subject=subject,
                    action_type="MEMO_APPROVED",
                    actor_user=request.user,
                    description=f"تم اعتماد المذكرة رقم {memo.memo_number}",
                )
                if memo.author_id != request.user.id:
                    NotificationService.notify(
                        recipient=memo.author,
                        subject=subject,
                        category=Notification.Category.DECISION_TASK,
                        priority=getattr(subject.priority, "code", "NORMAL"),
                        title=f"تم اعتماد المذكرة {memo.memo_number}",
                        message=f"اعتمد {request.user} المذكرة «{memo.title}» على الموضوع {subject.internal_number}.",
                        link_url=f"/subjects/{subject.id}/",
                    )
                messages.success(request, "تم اعتماد المذكرة بنجاح.")

            elif action == "add_annotation":
                if not PermissionService.user_has_permission(
                    request.user, "ANNOTATION_CREATE", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject
                ):
                    raise PermissionDenied("ليس لديك صلاحية تسجيل تأشيرة إدارية.")
                doc_id = request.POST.get("document_id") or None
                unit_id = request.POST.get("assigned_unit_id") or None
                ann = Annotation.objects.create(
                    subject=subject,
                    document_id=doc_id,
                    author=request.user,
                    recorded_by=request.user,
                    annotation_text=request.POST.get("annotation_text", "").strip(),
                    required_action=request.POST.get("required_action", "").strip(),
                    assigned_unit_id=unit_id,
                )
                AuditService.record_activity(
                    subject=subject,
                    action_type="ANNOTATION_ADDED",
                    actor_user=request.user,
                    description=f"تأشيرة إدارية: {ann.annotation_text[:120]} — الإجراء المطلوب: {ann.required_action}",
                )
                messages.success(request, "تم تسجيل التأشيرة الإدارية.")

            elif action == "suspend":
                if not PermissionService.user_has_permission(
                    request.user, "SUBJECT_SUSPEND", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject
                ):
                    raise PermissionDenied("ليس لديك صلاحية تعليق الموضوع.")
                reason_ref_id = request.POST.get("reason_ref_id") or None
                reason_ref = SuspensionReason.objects.filter(id=reason_ref_id).first() if reason_ref_id else None
                SubjectService.suspend_subject(
                    subject=subject,
                    user=request.user,
                    reason_ref=reason_ref,
                    reason_details=request.POST.get("reason_details", "").strip(),
                    required_from=request.POST.get("required_from", "").strip(),
                    required_item=request.POST.get("required_item", "").strip(),
                    expected_follow_up_date=request.POST.get("expected_follow_up_date") or None,
                )
                messages.warning(request, "تم تعليق الموضوع لحين استيفاء المطلوب.")

            elif action == "fulfill_suspension":
                suspension = get_object_or_404(SubjectSuspension, id=request.POST.get("suspension_id"), subject=subject)
                fulfillment_notes = request.POST.get("fulfillment_notes", "").strip() or "تم استيفاء المطلوب واستئناف العمل"
                resume_status = request.POST.get("resume_status") or Subject.Status.IN_PROGRESS
                fulfill_file = request.FILES.get("fulfillment_attachment")
                if fulfill_file is not None:
                    DocumentService.validate_uploaded_file(fulfill_file)
                SubjectService.fulfill_suspension(
                    suspension=suspension,
                    user=request.user,
                    fulfillment_notes=fulfillment_notes,
                    resume_status=resume_status,
                )
                if fulfill_file is not None:
                    doc_type_id = request.POST.get("fulfillment_doc_type_id")
                    chosen_doc_type = (
                        DocumentType.objects.filter(id=doc_type_id, is_active=True).first()
                        if doc_type_id
                        else DocumentType.objects.filter(is_active=True).first()
                    )
                    if chosen_doc_type:
                        DocumentService.register_document(
                            title=f"مستند استيفاء التعليق: {suspension.required_item}",
                            doc_type=chosen_doc_type,
                            confidentiality=subject.confidentiality,
                            created_by=request.user,
                            summary=fulfillment_notes,
                            subject=subject,
                            is_primary_subject=False,
                            relation_type=SubjectDocumentLink.RelationType.SUPPORTING,
                            uploaded_file=fulfill_file,
                        )
                messages.success(request, "تم تسجيل الاستيفاء وإرفاق المستند واستئناف مسار الموضوع.")

            elif action == "close_subject":
                exceptional = request.POST.get("exceptional") == "on"
                SubjectService.close_subject(
                    subject=subject,
                    user=request.user,
                    closure_notes=request.POST.get("closure_notes", ""),
                    exceptional=exceptional,
                )
                messages.success(request, "تم إغلاق الموضوع وأرشفته رسمياً.")

            elif action == "reopen_subject":
                SubjectService.reopen_subject(
                    subject=subject,
                    user=request.user,
                    reason=request.POST.get("reopen_reason", ""),
                )
                messages.info(request, "تم إعادة فتح الموضوع مع الاحتفاظ بسجل الإغلاق السابق.")

            elif action == "grant_access":
                if not PermissionService.user_has_permission(
                    request.user, "PERMISSIONS_MANAGE", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject
                ):
                    raise PermissionDenied("ليس لديك صلاحية تعديل استثناءات الوصول.")
                target_user = get_object_or_404(User, id=request.POST.get("target_user_id"))
                access_type = request.POST.get("access_type", SubjectAccessGrant.AccessType.GRANT)
                SubjectAccessGrant.objects.update_or_create(
                    subject=subject,
                    user=target_user,
                    defaults={
                        "access_type": access_type,
                        "granted_by": request.user,
                        "reason": request.POST.get("access_reason", ""),
                    },
                )
                messages.success(request, "تم تحديث استثناء الصلاحية للموضوع.")

            elif action == "apply_template":
                if not PermissionService.user_has_permission(
                    request.user, "REFERRAL_CREATE", sector=subject.sector, confidentiality_rank=subject.confidentiality.rank, subject=subject
                ):
                    raise PermissionDenied("ليس لديك صلاحية تطبيق قالب مسار عمل.")
                tpl_ver = WorkflowTemplateVersion.objects.filter(
                    id=request.POST.get("template_version_id"), is_active=True, template__is_active=True
                ).first()
                created_refs = apply_template(subject, tpl_ver, request.user)
                messages.success(request, f"تم تطبيق قالب مسار العمل وإنشاء {len(created_refs)} إحالة بنجاح.")

        except (ValidationError, OptimisticLockError) as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))

        return redirect("subjects:subject_detail", subject_id=subject.id)

    doc_links = list(
        SubjectDocumentLink.objects.filter(subject=subject)
        .select_related("document__doc_type", "document__confidentiality", "document__created_by")
        .prefetch_related("document__versions__attachments")
    )
    doc_links = [link for link in doc_links if PermissionService.can_view_document(request.user, link.document)]
    selected_doc_type = request.GET.get("doc_type", "").strip()

    # تجميع المرفقات حسب نوع المستند (doc_type)
    groups_map = {}
    for link in doc_links:
        dt = link.document.doc_type
        key = str(dt.id)
        if key not in groups_map:
            groups_map[key] = {"doc_type": dt, "links": [], "count": 0}
        groups_map[key]["links"].append(link)
        groups_map[key]["count"] += 1

    all_doc_groups = list(groups_map.values())
    filtered_doc_groups = (
        [g for g in all_doc_groups if str(g["doc_type"].id) == selected_doc_type]
        if selected_doc_type
        else all_doc_groups
    )

    referrals = list(
        Referral.objects.filter(subject=subject)
        .select_related("referred_by")
        .prefetch_related("recipients__target_user", "recipients__target_unit", "recipients__received_by")
        .order_by("created_at")
    )
    for ref_item in referrals:
        recs = list(ref_item.recipients.all())
        ref_item.can_withdraw = (
            not ref_item.is_completed
            and not ref_item.is_withdrawn
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
    tasks = Task.objects.filter(subject=subject).select_related("assigned_to", "assigned_unit", "assigned_by")
    memos = list(Memo.objects.filter(subject=subject).select_related("author", "approved_by"))
    annotations = Annotation.objects.filter(subject=subject).select_related("author", "assigned_unit", "document")
    committee_items = CommitteeAgendaItem.objects.filter(subject=subject).select_related("meeting__committee")
    decisions = list(
        Decision.objects.filter(subject=subject).prefetch_related(
            "distributions__target_unit", "execution_items__assigned_unit", "execution_items__assigned_user"
        )
    )
    suspensions = list(
        SubjectSuspension.objects.filter(subject=subject).select_related("reason_ref", "suspended_by", "fulfilled_by")
    )
    activity_logs = subject.activity_logs.select_related("actor_user", "acting_on_behalf_of").all()
    closure_blockers = SubjectService.validate_closure_requirements(subject)

    can_act = PermissionService.can_act_on_subject(request.user, subject)
    rank = subject.confidentiality.rank
    perms = {
        "can_act": can_act,
        "can_edit": can_act and PermissionService.user_has_permission(request.user, "SUBJECT_EDIT", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_refer": can_act and PermissionService.user_has_permission(request.user, "REFERRAL_CREATE", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_task": can_act and PermissionService.user_has_permission(request.user, "TASK_CREATE", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_memo": can_act and PermissionService.user_has_permission(request.user, "MEMO_CREATE", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_approve": can_act and PermissionService.user_has_permission(request.user, "APPROVAL_GRANT", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_annotate": can_act and PermissionService.user_has_permission(request.user, "ANNOTATION_CREATE", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_suspend": can_act and PermissionService.user_has_permission(request.user, "SUBJECT_SUSPEND", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_decide": can_act and PermissionService.user_has_permission(request.user, "DECISION_CREATE", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_approve_decision": PermissionService.user_has_permission(request.user, "DECISION_APPROVE", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_close": can_act and PermissionService.user_has_permission(request.user, "SUBJECT_CLOSE", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_exceptional_close": can_act and PermissionService.user_has_permission(request.user, "SUBJECT_EXCEPTIONAL_CLOSE", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_reopen": PermissionService.user_has_permission(request.user, "SUBJECT_REOPEN", sector=subject.sector, confidentiality_rank=rank, subject=subject),
        "can_manage_access": PermissionService.user_has_permission(request.user, "PERMISSIONS_MANAGE", sector=subject.sector, confidentiality_rank=rank, subject=subject),
    }

    # حساب مسار الـ 5 خطوات التنفيذي للعرض المبسط
    has_sector_or_gm_ref = len(referrals) > 0
    has_sup_or_emp_ref = any(
        any(
            rec.target_user
            and bool(PermissionService.get_effective_role_codes(rec.target_user, sector=subject.sector) & {"SUPERVISOR", "SPECIALIST"})
            for rec in r.recipients.all()
        )
        for r in referrals
    )
    has_memo = len(memos) > 0
    is_closed = subject.status == Subject.Status.CLOSED
    active_step = 5 if is_closed else (4 if (has_memo or has_sup_or_emp_ref) else (3 if has_sector_or_gm_ref else 2))
    workflow_steps = [
        {"id": 1, "title": "التسجيل والمرفقات", "done": True, "current": False},
        {"id": 2, "title": "توجيه القطاع والمدير العام", "done": active_step > 2 or has_sector_or_gm_ref, "current": not is_closed and active_step == 2},
        {"id": 3, "title": "التوزيع على القسم والمختص", "done": active_step > 3 or has_sup_or_emp_ref, "current": not is_closed and active_step == 3},
        {"id": 4, "title": "إعداد المذكرة والقرار", "done": is_closed or has_memo or len(decisions) > 0, "current": not is_closed and active_step == 4},
        {"id": 5, "title": "الاعتماد والإغلاق والأرشفة", "done": is_closed, "current": not is_closed and active_step == 5},
    ]

    # إرشاد للموظف المختص عند امتلاك العهدة
    role_codes = PermissionService.get_effective_role_codes(request.user, sector=subject.sector)
    is_specialist_acting = ("SPECIALIST" in role_codes) and can_act and not is_closed
    resume_status_choices = [
        (Subject.Status.IN_PROGRESS, "قيد التنفيذ (استكمال الدراسة)"),
        (Subject.Status.UNDER_REVIEW, "قيد المراجعة"),
        (Subject.Status.AWAITING_APPROVAL, "في انتظار اعتماد"),
    ]

    # بناء مراحل خط السير الجانبي (مفتوح افتراضياً مع من ← إلى)
    workflow_stages = []
    creator_label = (subject.created_by.get_full_name() or subject.created_by.username) if subject.created_by else "السجل العام"
    owner_label = (subject.current_owner.get_full_name() or subject.current_owner.username) if subject.current_owner else (subject.org_unit.name if subject.org_unit else "قيد التعيين")
    stage_num = 1
    workflow_stages.append(
        {
            "stage_number": stage_num,
            "title": "تسجيل المعاملة وفتح الملف",
            "from_label": subject.external_source or "الوارد العام",
            "to_label": creator_label,
            "date": subject.created_at.strftime("%Y-%m-%d %H:%M") if subject.created_at else "",
            "what_happened": f"تم تسجيل الموضوع برقم ({subject.internal_number}) وتصنيف السرية ({subject.confidentiality.name if subject.confidentiality else 'عادي'}).",
            "required": "إرفاق المستندات الداعمة وتحديد أول مسار إحالة.",
            "completed_text": "تم التسجيل وتثبيت الرقم الأرشيفي بنجاح",
            "pending_text": "" if referrals else "بانتظار الإحالة والتوجيه الأول",
            "status": "completed" if (referrals or is_closed) else "active",
        }
    )

    for idx_r, ref in enumerate(referrals):
        stage_num += 1
        rec_list = list(ref.recipients.all())
        rec_names = "، ".join(
            [
                (r.target_user.get_full_name() or r.target_user.username)
                if r.target_user
                else (r.target_unit.name if r.target_unit else "جهة")
                for r in rec_list
            ]
        ) or owner_label
        is_ack = any(r.status == ReferralRecipient.RecipientStatus.RECEIVED for r in rec_list)
        has_next = idx_r < len(referrals) - 1 or has_memo or len(decisions) > 0 or is_closed
        workflow_stages.append(
            {
                "stage_number": stage_num,
                "title": f"إحالة {ref.get_purpose_display()}",
                "from_label": (ref.referred_by.get_full_name() or ref.referred_by.username) if ref.referred_by else creator_label,
                "to_label": rec_names,
                "date": ref.created_at.strftime("%Y-%m-%d %H:%M") if ref.created_at else "",
                "what_happened": ref.notes or f"توجيه الموضوع ({ref.get_purpose_display()}) لمتابعة الدراسة والتنفيذ.",
                "required": "الاستلام الرسمي ودراسة المرفقات وإبداء الرأي.",
                "completed_text": "تم التوجيه والاستلام" if (is_ack or has_next) else "تم إرسال الإحالة",
                "pending_text": "" if (is_ack or has_next) else "بانتظار تأكيد الاستلام أو الرد",
                "status": "completed" if (is_ack or has_next) else "active",
            }
        )

    for susp in suspensions:
        stage_num += 1
        workflow_stages.append(
            {
                "stage_number": stage_num,
                "title": f"تعليق استيفاء ({susp.reason_ref.name if susp.reason_ref else 'مستندات'})",
                "from_label": (susp.suspended_by.get_full_name() or susp.suspended_by.username) if susp.suspended_by else owner_label,
                "to_label": (susp.fulfilled_by.get_full_name() or susp.fulfilled_by.username) if susp.fulfilled_by else (susp.required_from or "الجهة الطالبة / المختص"),
                "date": susp.suspended_at.strftime("%Y-%m-%d %H:%M") if susp.suspended_at else "",
                "what_happened": susp.reason_details or "إيقاف المسار مؤقتاً لحين استيفاء المطلوب.",
                "required": susp.required_item or "استيفاء المستندات المطلوبة لاستئناف المسار.",
                "completed_text": "تم تسجيل الاستيفاء واستئناف المسار" if susp.is_fulfilled else "تم تعليق المسار بانتظار الاستيفاء",
                "pending_text": "" if susp.is_fulfilled else "بانتظار رفع مستندات الاستيفاء",
                "status": "completed" if susp.is_fulfilled else "waiting",
            }
        )

    for memo in memos:
        stage_num += 1
        workflow_stages.append(
            {
                "stage_number": stage_num,
                "title": f"مذكرة عرض ({memo.get_memo_type_display()})",
                "from_label": (memo.author.get_full_name() or memo.author.username) if memo.author else owner_label,
                "to_label": memo.directed_to or (memo.approved_by.get_full_name() if memo.approved_by else "السلطة المختصة"),
                "date": memo.created_at.strftime("%Y-%m-%d %H:%M") if memo.created_at else "",
                "what_happened": (memo.body[:160] + "…") if memo.body and len(memo.body) > 160 else (memo.body or memo.title),
                "required": "مراجعة الرأي والتوصية والاعتماد.",
                "completed_text": f"مذكرة معتمدة ({memo.get_status_display()})" if memo.status == Memo.MemoStatus.APPROVED else f"حالة المذكرة: {memo.get_status_display()}",
                "pending_text": "" if (memo.status == Memo.MemoStatus.APPROVED or is_closed) else "بانتظار الاعتماد أو التعديل",
                "status": "completed" if (memo.status == Memo.MemoStatus.APPROVED or is_closed) else "active",
            }
        )

    for dec in decisions:
        stage_num += 1
        dec_done = dec.status in {"APPROVED", "ISSUED", "DISTRIBUTING", "EXECUTING", "COMPLETED"}
        workflow_stages.append(
            {
                "stage_number": stage_num,
                "title": f"قرار إداري ({dec.decision_number or 'مسودة'})",
                "from_label": owner_label,
                "to_label": "جهات التنفيذ والتوزيع",
                "date": dec.created_at.strftime("%Y-%m-%d %H:%M") if dec.created_at else "",
                "what_happened": dec.title,
                "required": "اعتماد القرار وتوزيعه وتأكيد إثبات التنفيذ.",
                "completed_text": f"تم التنفيذ والاعتماد ({dec.get_status_display()})" if dec_done else f"حالة القرار: {dec.get_status_display()}",
                "pending_text": "" if (dec_done or is_closed) else "بانتظار اعتماد أو إثبات تنفيذ القرار",
                "status": "completed" if (dec_done or is_closed) else "active",
            }
        )

    if is_closed:
        stage_num += 1
        workflow_stages.append(
            {
                "stage_number": stage_num,
                "title": "الاعتماد والإغلاق والأرشفة الرسمية",
                "from_label": owner_label,
                "to_label": "الأرشيف الدائم",
                "date": subject.closed_at.strftime("%Y-%m-%d %H:%M") if subject.closed_at else "",
                "what_happened": subject.closure_notes or "تم استيفاء جميع المتطلبات وإغلاق الموضوع أرشيفياً.",
                "required": "حفظ السلسلة وسجل التدقيق غير قابل للتعديل.",
                "completed_text": "تم الإغلاق والأرشفة النهائية بنجاح",
                "pending_text": "",
                "status": "completed",
            }
        )

    completed_stages_count = sum(1 for st in workflow_stages if st["status"] == "completed")
    active_stage_pending_text = next(
        (st["pending_text"] for st in reversed(workflow_stages) if st.get("pending_text")),
        "مكتمل ومغلق نهائياً" if is_closed else "قيد المتابعة لدى المالك الحالي",
    )

    pending_recipient = None
    for ref_item in referrals:
        for rec in ref_item.recipients.all():
            if rec.is_active_step and rec.status == ReferralRecipient.RecipientStatus.PENDING and (
                rec.target_user_id == request.user.id
                or (not rec.target_user_id and request.user.current_unit_id and rec.target_unit_id == request.user.current_unit_id)
            ):
                pending_recipient = rec
                break
        if pending_recipient:
            break

    draft_memo = next((m for m in memos if m.status != Memo.MemoStatus.APPROVED), None)

    return render(
        request,
        "subjects/subject_detail.html",
        {
            "subject": subject,
            "doc_links": doc_links,
            "all_doc_groups": all_doc_groups,
            "filtered_doc_groups": filtered_doc_groups,
            "selected_doc_type": selected_doc_type,
            "doc_types": DocumentType.objects.filter(is_active=True),
            "referrals": referrals,
            "pending_recipient": pending_recipient,
            "tasks": tasks,
            "memos": memos,
            "draft_memo": draft_memo,
            "annotations": annotations,
            "committee_items": committee_items,
            "decisions": decisions,
            "suspensions": suspensions,
            "activity_logs": activity_logs,
            "closure_blockers": closure_blockers,
            "workflow_steps": workflow_steps,
            "guide": build_subject_guidance(
                subject,
                perms,
                pending_recipient=pending_recipient,
                has_memo=has_memo,
                decisions_count=len(decisions),
                referrals_count=len(referrals),
                docs_count=len(doc_links),
                closure_blockers=closure_blockers,
                active_step=active_step,
                is_closed=is_closed,
            ),
            "workflow_stages": workflow_stages,
            "completed_stages_count": completed_stages_count,
            "active_stage_pending_text": active_stage_pending_text,
            "is_specialist_acting": is_specialist_acting,
            "perms": perms,
            "org_units": OrgUnit.objects.filter(is_active=True),
            "users": User.objects.filter(is_active=True),
            "suspension_reasons": SuspensionReason.objects.filter(is_active=True),
            "resume_status_choices": resume_status_choices,
            "all_documents": Document.objects.all()[:50],
            "memo_types": MemoTypeRef.objects.filter(is_active=True),
            "memo_directed_targets": MemoRecipientRef.objects.filter(is_active=True),
            "template_versions": WorkflowTemplateVersion.objects.filter(
                is_active=True, template__is_active=True
            ).select_related("template", "template__transaction_type", "template__sector"),
            "reassign_candidates": (
                User.objects.filter(is_active=True)
                if (request.user.is_superuser or PermissionService.is_org_wide_manager(request.user))
                else User.objects.filter(is_active=True, employee__current_unit__sector=subject.sector)
            ),
        },
    )


@login_required
def subject_preview_json(request, subject_id: int):
    """بيانات المعاينة الفورية للوحة القراءة الجانبية في صندوق البريد الوارد (Split Reading Panel)."""
    subject = get_object_or_404(
        Subject.objects.select_related(
            "transaction_type",
            "sector",
            "org_unit",
            "confidentiality",
            "priority",
            "current_owner",
            "created_by",
        ),
        id=subject_id,
    )
    if not PermissionService.can_view_subject(request.user, subject):
        raise PermissionDenied("غير مصرح لك بالاطلاع على هذا الموضوع أو مستوى سريته.")

    can_act = PermissionService.can_act_on_subject(request.user, subject)
    pending_rec = (
        ReferralRecipient.objects.filter(
            referral__subject=subject,
            target_user=request.user,
            status=ReferralRecipient.RecipientStatus.PENDING,
            is_active_step=True,
        )
        .select_related("referral")
        .first()
    )

    attachments_data = []
    doc_links = (
        SubjectDocumentLink.objects.filter(subject=subject)
        .select_related("document__doc_type", "document__confidentiality")
        .prefetch_related("document__versions__attachments")
    )
    for link in doc_links:
        if not PermissionService.can_view_document(request.user, link.document):
            continue
        for ver in link.document.versions.all():
            for att in ver.attachments.all():
                download_url = reverse("documents:attachment_download", args=[att.id])
                full_page_url = reverse("documents:attachment_preview", args=[att.id])
                attachments_data.append(
                    {
                        "id": att.id,
                        "filename": att.original_filename,
                        "doc_title": link.document.title,
                        "doc_type": link.document.doc_type.name,
                        "preview_kind": att.preview_kind,
                        "file_size": att.file_size,
                        "preview_url": f"{download_url}?inline=1&mode=stream",
                        "download_url": download_url,
                        "full_page_url": full_page_url,
                    }
                )

    recent_referrals = []
    for ref in subject.referrals.select_related("referred_by").prefetch_related("recipients__target_user", "recipients__target_unit").order_by("-created_at")[:3]:
        targets = [str(r.target_user or r.target_unit) for r in ref.recipients.all()]
        recent_referrals.append(
            {
                "referred_by": str(ref.referred_by),
                "purpose": ref.get_purpose_display(),
                "targets": "، ".join(targets) or "—",
                "notes": ref.notes,
                "created_at": ref.created_at.strftime("%Y-%m-%d %H:%M"),
            }
        )

    return JsonResponse(
        {
            "id": subject.id,
            "internal_number": subject.internal_number,
            "title": subject.title,
            "description": subject.description,
            "status_label": subject.get_status_display(),
            "confidentiality": subject.confidentiality.name,
            "is_top_secret": subject.confidentiality.overrides_hierarchy,
            "priority": subject.priority.name,
            "transaction_type": subject.transaction_type.name,
            "sector": subject.sector.name,
            "org_unit": subject.org_unit.name,
            "current_owner": str(subject.current_owner),
            "due_date": str(subject.due_date) if subject.due_date else "غير محدد",
            "is_overdue": subject.is_overdue,
            "can_act": can_act,
            "pending_ref_id": pending_rec.id if pending_rec else None,
            "memos_count": subject.memos.count(),
            "attachments": attachments_data,
            "recent_referrals": recent_referrals,
            "detail_url": reverse("subjects:subject_detail", args=[subject.id]),
            "ack_url": reverse("workflow:referral_respond", args=[pending_rec.id]) if pending_rec else None,
        }
    )


@login_required
def memo_print(request, memo_id: int):
    """قالب طباعة رسمي للمذكرة بالاتجاه العربي RTL."""
    memo = get_object_or_404(Memo.objects.select_related("subject", "author", "approved_by"), id=memo_id)
    if not PermissionService.can_view_subject(request.user, memo.subject):
        raise PermissionDenied("غير مصرح لك بطباعة هذه المذكرة.")
    return render(request, "subjects/memo_print.html", {"memo": memo})


@login_required
def subject_export_pdf(request, subject_id: int):
    """تصدير ملف الموضوع وسلسلة الإحالات والمذكرات والقرارات كملف PDF مؤسسي."""
    subject = get_object_or_404(
        Subject.objects.select_related(
            "transaction_type", "sector", "org_unit", "confidentiality", "priority", "current_owner", "created_by"
        ).prefetch_related("referrals__referred_by", "referrals__recipients__target_user", "memos__author", "decisions"),
        id=subject_id,
    )
    if not PermissionService.can_view_subject(request.user, subject):
        raise PermissionDenied("غير مصرح لك بتصدير هذا الموضوع.")

    ref_lines = []
    for ref in subject.referrals.all():
        tgts = ", ".join(str(r.target_user or r.target_unit) for r in ref.recipients.all()) or "-"
        ref_lines.append(f"{ref.created_at:%Y-%m-%d %H:%M} | {ref.referred_by} -> {tgts} | {ref.notes or '-'}")

    memo_lines = [
        f"{m.memo_number} | {m.title} | To: {m.directed_to} | Status: {m.get_status_display()}"
        for m in subject.memos.all()
    ]
    decision_lines = [
        f"{d.decision_number} | {d.title} | Status: {d.get_status_display()}"
        for d in subject.decisions.all()
    ]

    pdf_bytes = build_institutional_pdf_bytes(
        title=f"Subject {subject.internal_number} - {subject.title}",
        subtitle=f"Sector: {subject.sector.name} | Unit: {subject.org_unit.name}",
        metadata_rows=[
            ("Internal Number", subject.internal_number),
            ("Status", subject.get_status_display()),
            ("Confidentiality", subject.confidentiality.name),
            ("Priority", subject.priority.name),
            ("Current Owner", str(subject.current_owner)),
            ("External Source", subject.external_source or "-"),
            ("Due Date", str(subject.due_date or "-")),
        ],
        sections=[
            {"heading": "Description", "lines": [subject.description or "-"]},
            {"heading": "Referrals History", "lines": ref_lines or ["-"]},
            {"heading": "Memos", "lines": memo_lines or ["-"]},
            {"heading": "Decisions", "lines": decision_lines or ["-"]},
        ],
    )
    AuditService.log_audit(
        actor=request.user,
        action="SUBJECT_EXPORT_PDF",
        model_name="Subject",
        object_id=subject.id,
        after_state={"internal_number": subject.internal_number},
    )
    return pdf_http_response(pdf_bytes, f"subject_{subject.internal_number}.pdf", inline=request.GET.get("inline") == "1")


@login_required
def memo_export_pdf(request, memo_id: int):
    """تصدير مذكرة عرض رسمية إلى ملف PDF مؤسسي مباشر."""
    memo = get_object_or_404(Memo.objects.select_related("subject", "author", "approved_by"), id=memo_id)
    if not PermissionService.can_view_subject(request.user, memo.subject):
        raise PermissionDenied("غير مصرح لك بتصدير هذه المذكرة.")

    pdf_bytes = build_institutional_pdf_bytes(
        title=f"Memo {memo.memo_number} - {memo.title}",
        subtitle=f"Subject: {memo.subject.internal_number} | Directed To: {memo.directed_to}",
        metadata_rows=[
            ("Memo Number", memo.memo_number),
            ("Memo Type", memo.get_memo_type_display()),
            ("Subject", f"{memo.subject.internal_number} - {memo.subject.title}"),
            ("Author", str(memo.author)),
            ("Approved By", str(memo.approved_by or "-")),
            ("Status", memo.get_status_display()),
            ("Date", memo.created_at.strftime("%Y-%m-%d %H:%M")),
        ],
        sections=[{"heading": "Memo Body", "lines": (memo.body or "-").splitlines()}],
    )
    return pdf_http_response(pdf_bytes, f"memo_{memo.memo_number}.pdf", inline=request.GET.get("inline") == "1")
