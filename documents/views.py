from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from accounts.services import PermissionService
from audit.services import AuditService
from core.models import ConfidentialityLevel, DocumentType
from core.pdf_utils import build_institutional_pdf_bytes, pdf_http_response
from subjects.models import Subject
from .models import Attachment, Document, DocumentVersion, SubjectDocumentLink
from .office_preview import extract_office_preview_html
from .services import DocumentService


@login_required
def document_list(request):
    """قائمة المستندات مع البحث السريع وتصفية السرية وعزل القطاعات والتصفح بالصفحات."""
    q = request.GET.get("q", "").strip()
    docs = Document.objects.select_related(
        "doc_type", "confidentiality", "created_by__employee__current_unit__sector"
    ).prefetch_related(
        "subjects__confidentiality", "subjects__sector", "subjects__org_unit", "versions__attachments"
    )
    if q:
        docs = docs.filter(
            Q(title__icontains=q)
            | Q(summary__icontains=q)
            | Q(internal_number__icontains=q)
            | Q(external_in_out_number__icontains=q)
        )
    visible_docs = []
    for doc in docs:
        if PermissionService.can_view_document(request.user, doc):
            latest_att = None
            for ver in doc.versions.all():
                atts = list(ver.attachments.all())
                if atts:
                    latest_att = atts[0]
                    break
            doc.primary_attachment = latest_att
            visible_docs.append(doc)

    paginator = Paginator(visible_docs, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "documents/document_list.html",
        {
            "documents": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "total_count": paginator.count,
            "q": q,
        },
    )


@login_required
def document_create(request):
    """تسجيل مستند جديد (وارد/صادر/داخلي) وربطه بموضوع مع دعم تعدد المرفقات والتحقق الأمني."""
    if not PermissionService.user_has_permission(request.user, "DOCUMENT_CREATE"):
        raise PermissionDenied("ليس لديك صلاحية تسجيل المستندات.")

    subject_id = request.GET.get("subject_id") or request.POST.get("subject_id")
    selected_subject = Subject.objects.filter(id=subject_id).first() if subject_id else None
    if selected_subject:
        if not PermissionService.can_view_subject(request.user, selected_subject):
            raise PermissionDenied("غير مصرح لك بالوصول للموضوع المحدد.")
        if not PermissionService.can_act_on_subject(request.user, selected_subject):
            raise PermissionDenied("لا يمكنك إرفاق مستندات على موضوع للاطلاع فقط في مستواك الحالي.")

    if request.method == "POST":
        conf = get_object_or_404(ConfidentialityLevel, id=request.POST.get("confidentiality_id"))
        target_sector = selected_subject.sector if selected_subject else request.user.current_sector
        if not PermissionService.user_has_permission(
            request.user,
            "DOCUMENT_CREATE",
            sector=target_sector,
            confidentiality_rank=conf.rank,
            subject=selected_subject,
        ):
            raise PermissionDenied("ليس لديك صلاحية تسجيل مستند بهذا المستوى من السرية.")

        try:
            files = request.FILES.getlist("attachment_file")
            doc = DocumentService.register_document(
                title=request.POST.get("title", "").strip(),
                doc_type=get_object_or_404(DocumentType, id=request.POST.get("doc_type_id")),
                confidentiality=conf,
                created_by=request.user,
                source_type=request.POST.get("source_type", Document.SourceType.INCOMING),
                external_in_out_number=request.POST.get("external_in_out_number", "").strip(),
                document_date=request.POST.get("document_date") or None,
                received_date=request.POST.get("received_date") or None,
                sender_entity=request.POST.get("sender_entity", "").strip(),
                receiver_entity=request.POST.get("receiver_entity", "").strip(),
                summary=request.POST.get("summary", "").strip(),
                subject=selected_subject,
                relation_type=request.POST.get("relation_type", SubjectDocumentLink.RelationType.PRIMARY),
                uploaded_files=files,
                attachment_description=request.POST.get("attachment_description", ""),
            )
            messages.success(request, f"تم تسجيل المستند بالرقم الداخلي {doc.internal_number}.")
            if selected_subject:
                return redirect("subjects:subject_detail", subject_id=selected_subject.id)
            return redirect("documents:document_detail", doc_id=doc.id)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))

    visible_subjects = PermissionService.filter_visible_subjects(Subject.objects.all(), request.user)
    return render(
        request,
        "documents/document_form.html",
        {
            "doc_types": DocumentType.objects.filter(is_active=True),
            "confidentialities": ConfidentialityLevel.objects.filter(is_active=True),
            "subjects": visible_subjects,
            "selected_subject": selected_subject,
        },
    )


@login_required
def document_detail(request, doc_id: int):
    """تفاصيل المستند ونسخه ومرفقاته وفحص سلامة SHA-256 وربطه بأكثر من موضوع مع حماية السرية."""
    doc = get_object_or_404(
        Document.objects.select_related(
            "doc_type", "confidentiality", "created_by__employee__current_unit__sector"
        ).prefetch_related("versions__attachments__uploaded_by", "subjectdocumentlink_set__subject"),
        id=doc_id,
    )
    if not PermissionService.can_view_document(request.user, doc):
        AuditService.log_audit(
            actor=request.user,
            action="UNAUTHORIZED_DOCUMENT_ACCESS",
            model_name="Document",
            object_id=doc.id,
            outcome="DENIED",
        )
        raise PermissionDenied("غير مصرح لك بالاطلاع على هذا المستند أو مستوى سريته.")

    linked_subjects = [link.subject for link in doc.subjectdocumentlink_set.all()]
    context_subject = linked_subjects[0] if linked_subjects else None
    context_sector = (
        context_subject.sector
        if context_subject is not None
        else (doc.created_by.current_sector if doc.created_by else None)
    )

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "new_version":
                if not PermissionService.user_has_permission(
                    request.user,
                    "DOCUMENT_CREATE",
                    sector=context_sector,
                    confidentiality_rank=doc.confidentiality.rank,
                    subject=context_subject,
                ):
                    raise PermissionDenied("ليس لديك صلاحية إصدار نسخة جديدة لهذا المستند السري.")
                if linked_subjects:
                    if not request.user.is_superuser and not any(
                        PermissionService.can_act_on_subject(request.user, s) for s in linked_subjects
                    ):
                        raise PermissionDenied("لا يمكنك إصدار نسخة جديدة على مستند لموضوع ليس في عهدتك.")
                elif not request.user.is_superuser and doc.created_by_id != request.user.id:
                    raise PermissionDenied("تحديث مستند مستقل متاح لمنشئ المستند أو Superuser فقط.")

                want_approve = request.POST.get("is_approved") == "on"
                if want_approve and not PermissionService.user_has_permission(
                    request.user,
                    "APPROVAL_GRANT",
                    sector=context_sector,
                    confidentiality_rank=doc.confidentiality.rank,
                    subject=context_subject,
                ):
                    raise PermissionDenied("ليس لديك صلاحية اعتماد نسخة مستند.")

                DocumentService.create_new_version(
                    document=doc,
                    user=request.user,
                    change_reason=request.POST.get("change_reason", "").strip(),
                    is_approved=want_approve,
                    uploaded_files=request.FILES.getlist("attachment_file"),
                    attachment_description=request.POST.get("attachment_description", ""),
                )
                messages.success(request, "تم إصدار نسخة جديدة من المستند مع الاحتفاظ بالنسخ السابقة.")

            elif action == "add_attachment":
                ver = get_object_or_404(DocumentVersion, id=request.POST.get("version_id"), document=doc)
                if not PermissionService.user_has_permission(
                    request.user,
                    "DOCUMENT_CREATE",
                    sector=context_sector,
                    confidentiality_rank=doc.confidentiality.rank,
                    subject=context_subject,
                ):
                    raise PermissionDenied("ليس لديك صلاحية إضافة مرفقات لهذا المستند.")
                DocumentService.add_attachments_to_version(
                    version=ver,
                    user=request.user,
                    uploaded_files=request.FILES.getlist("attachment_file"),
                    attachment_description=request.POST.get("attachment_description", ""),
                )
                messages.success(request, f"تمت إضافة المرفقات للنسخة v{ver.version_number}.")

            elif action == "approve_version":
                ver = get_object_or_404(DocumentVersion, id=request.POST.get("version_id"), document=doc)
                if not PermissionService.user_has_permission(
                    request.user,
                    "APPROVAL_GRANT",
                    sector=context_sector,
                    confidentiality_rank=doc.confidentiality.rank,
                    subject=context_subject,
                ):
                    raise PermissionDenied("ليس لديك صلاحية اعتماد إصدارات المستند.")
                DocumentService.approve_version(version=ver, user=request.user)
                messages.success(request, f"تم اعتماد النسخة v{ver.version_number} وتثبيتها ضد الاستبدال.")

            elif action == "link_subject":
                target_subject = get_object_or_404(Subject, id=request.POST.get("subject_id"))
                if not PermissionService.can_view_subject(request.user, target_subject):
                    raise PermissionDenied("غير مصرح لك بربط المستند بهذا الموضوع.")
                if not PermissionService.can_act_on_subject(request.user, target_subject):
                    raise PermissionDenied("لا يمكنك ربط مستند بموضوع ليس في عهدتك التنفيذية.")
                required_rank = max(doc.confidentiality.rank, target_subject.confidentiality.rank)
                if not PermissionService.user_has_permission(
                    request.user,
                    "DOCUMENT_CREATE",
                    sector=target_subject.sector,
                    confidentiality_rank=required_rank,
                    subject=target_subject,
                ):
                    raise PermissionDenied("ليس لديك صلاحية ربط المستندات بهذا المستوى من السرية.")

                SubjectDocumentLink.objects.get_or_create(
                    subject=target_subject,
                    document=doc,
                    defaults={
                        "relation_type": request.POST.get("relation_type", SubjectDocumentLink.RelationType.SUPPORTING),
                        "linked_by": request.user,
                    },
                )
                AuditService.record_activity(
                    subject=target_subject,
                    action_type="DOCUMENT_LINKED",
                    actor_user=request.user,
                    description=f"ربط المستند ({doc.internal_number}) بالموضوع",
                )
                messages.success(request, f"تم ربط المستند بالموضوع {target_subject.internal_number}.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("documents:document_detail", doc_id=doc.id)

    versions_data = []
    for ver in doc.versions.all():
        att_rows = []
        for att in ver.attachments.all():
            integrity = DocumentService.verify_attachment_integrity(att)
            att_rows.append({"att": att, "integrity": integrity})
        versions_data.append({"ver": ver, "attachments": att_rows})

    timeline_events = [{
        "title": "تسجيل المستند",
        "description": doc.title,
        "date": doc.created_at,
        "actor": doc.created_by.get_full_name() or doc.created_by.username,
    }]
    attachment_count = 0
    for row in versions_data:
        ver = row["ver"]
        timeline_events.append({
            "title": "إصدار نسخة معتمدة" if ver.is_approved else "إصدار نسخة",
            "description": f"النسخة v{ver.version_number}" + (f" — {ver.change_reason}" if ver.change_reason else ""),
            "date": ver.created_at,
            "actor": ver.created_by.get_full_name() or ver.created_by.username,
        })
        for attachment_row in row["attachments"]:
            att = attachment_row["att"]
            attachment_count += 1
            timeline_events.append({
                "title": "إضافة مرفق",
                "description": att.original_filename,
                "date": att.uploaded_at,
                "actor": att.uploaded_by.get_full_name() or att.uploaded_by.username,
            })
    linked_subjects = []
    for link in doc.subjectdocumentlink_set.all():
        linked_subject = link.subject
        # لا تكشف رقم الموضوع أو عنوانه أو حدث ربطه إلا لمن يملك صلاحية رؤية الموضوع نفسه.
        if not PermissionService.can_view_subject(request.user, linked_subject):
            continue
        linked_subject.document_relation_label = link.get_relation_type_display()
        linked_subjects.append(linked_subject)
        timeline_events.append({
            "title": "ربط بموضوع",
            "description": f"{linked_subject.internal_number} — {linked_subject.title}",
            "date": link.linked_at,
            "actor": link.linked_by.get_full_name() or link.linked_by.username,
        })
    timeline_events.sort(key=lambda event: event["date"], reverse=True)

    current_version = next((row["ver"] for row in versions_data if row["ver"].version_number == doc.current_version_number), None)

    visible_subjects = PermissionService.filter_visible_subjects(Subject.objects.all(), request.user)
    can_approve_doc = PermissionService.user_has_permission(
        request.user,
        "APPROVAL_GRANT",
        sector=context_sector,
        confidentiality_rank=doc.confidentiality.rank,
        subject=context_subject,
    )
    return render(
        request,
        "documents/document_detail.html",
        {
            "doc": doc,
            "versions_data": versions_data,
            "attachment_count": attachment_count,
            "current_version": current_version,
            "linked_subjects": linked_subjects,
            "linked_subject_count": len(linked_subjects),
            "timeline_events": timeline_events,
            "visible_subjects": visible_subjects,
            "can_approve_doc": can_approve_doc,
        },
    )


@login_required
def attachment_preview(request, attachment_id: int):
    """
    معاينة داخلية آمنة للمرفقات:
    - PDF عبر iframe
    - الصور عبر img مع التكبير
    - ملفات Office (DOCX/XLSX/DOC/XLS) عبر بطاقة توضح عدم توفر المعاينة وزر تنزيل منفصل
    - تطبيق نفس قواعد سرية المستند وSubjectAccessGrant وعزل القطاعات، وتسجيل كل معاينة سرية في AuditLog.
    """
    attachment = get_object_or_404(
        Attachment.objects.select_related(
            "document_version__document__doc_type",
            "document_version__document__confidentiality",
            "document_version__document__created_by__employee__current_unit__sector",
            "uploaded_by",
        ),
        id=attachment_id,
    )
    doc = attachment.document_version.document

    if not PermissionService.can_download_attachment(request.user, attachment):
        AuditService.log_audit(
            actor=request.user,
            action="UNAUTHORIZED_ATTACHMENT_ACCESS",
            model_name="Attachment",
            object_id=attachment.id,
            after_state={"document": doc.internal_number, "mode": "preview"},
            outcome="DENIED",
        )
        raise PermissionDenied("غير مصرح لك بمعاينة هذا المرفق أو مستوى سريته.")

    integrity = DocumentService.verify_attachment_integrity(attachment)
    if not integrity["ok"]:
        AuditService.log_audit(
            actor=request.user,
            action="ATTACHMENT_INTEGRITY_FAILED",
            model_name="Attachment",
            object_id=attachment.id,
            after_state={"document": doc.internal_number, "status": integrity["status"]},
            outcome="DENIED",
            reason=integrity["label"],
        )
    elif doc.confidentiality.rank >= 2 or doc.confidentiality.overrides_hierarchy:
        # تسجيل كل معاينة لمستند سري أو سري للغاية في AuditLog بعد نجاح التحقق
        AuditService.log_audit(
            actor=request.user,
            action="DOCUMENT_PREVIEW",
            model_name="Attachment",
            object_id=attachment.id,
            after_state={
                "internal_number": doc.internal_number,
                "confidentiality": doc.confidentiality.code,
                "attachment_id": attachment.id,
                "filename": attachment.original_filename,
            },
            outcome="SUCCESS",
        )

    text_preview = None
    office_preview_html = None
    if integrity["ok"] and integrity["vault_path"] is not None:
        if attachment.preview_kind in {"text", "csv", "json"}:
            try:
                text_preview = integrity["vault_path"].read_text(encoding="utf-8", errors="replace")[:30000]
            except Exception:
                text_preview = None
        elif attachment.preview_kind == "office":
            office_preview_html = extract_office_preview_html(integrity["vault_path"], attachment.original_filename)

    return render(
        request,
        "documents/attachment_preview.html",
        {
            "attachment": attachment,
            "doc": doc,
            "integrity": integrity,
            "text_preview": text_preview,
            "office_preview_html": office_preview_html,
        },
    )


@login_required
def attachment_download(request, attachment_id: int):
    """
    تنزيل أو بث المرفق للمعاينة عبر Django بعد التحقق الكامل من الصلاحيات والسرية
    والبصمة الرقمية SHA-256 وحماية المسار لمنع أي وصول مباشر للملفات على الخادم.
    """
    attachment = get_object_or_404(
        Attachment.objects.select_related(
            "document_version__document__confidentiality",
            "document_version__document__created_by__employee__current_unit__sector",
        ),
        id=attachment_id,
    )
    doc = attachment.document_version.document
    if not PermissionService.can_download_attachment(request.user, attachment):
        AuditService.log_audit(
            actor=request.user,
            action="UNAUTHORIZED_ATTACHMENT_ACCESS",
            model_name="Attachment",
            object_id=attachment.id,
            outcome="DENIED",
        )
        raise PermissionDenied("غير مصرح لك بتنزيل أو معاينة هذا المرفق.")

    integrity = DocumentService.verify_attachment_integrity(attachment)
    if integrity["status"] == "MISSING":
        raise Http404("ملف المرفق غير موجود في الخزينة المعزولة.")
    if not integrity["ok"] or integrity["vault_path"] is None:
        AuditService.log_audit(
            actor=request.user,
            action="ATTACHMENT_INTEGRITY_FAILED",
            model_name="Attachment",
            object_id=attachment.id,
            after_state={"status": integrity["status"]},
            outcome="DENIED",
            reason=integrity["label"],
        )
        raise PermissionDenied("تعذر تقديم الملف: محتوى المرفق تالف أو لا يطابق بصمة SHA-256 الأصلية.")

    if request.GET.get("mode") == "office_html":
        html_fragment = extract_office_preview_html(integrity["vault_path"], attachment.original_filename)
        resp = HttpResponse(html_fragment, content_type="text/html; charset=utf-8")
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "no-store, private"
        return resp

    if request.GET.get("raw") == "1":
        raw_bytes = integrity["vault_path"].read_bytes()[:32768]
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        resp = HttpResponse(raw_text, content_type="text/plain; charset=utf-8")
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "no-store, private"
        return resp

    mime_lower = (attachment.mime_type or "").lower()
    inline_allowed_mimes = {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "image/bmp",
        "image/svg+xml",
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/tab-separated-values",
        "text/yaml",
        "application/json",
        "application/xml",
    }
    inline = request.GET.get("inline") == "1" and (
        mime_lower in inline_allowed_mimes
        or mime_lower.startswith("audio/")
        or mime_lower.startswith("video/")
    )
    stream_mode = request.GET.get("mode") == "stream"

    if not stream_mode:
        if inline and (doc.confidentiality.rank >= 2 or doc.confidentiality.overrides_hierarchy):
            AuditService.log_audit(
                actor=request.user,
                action="DOCUMENT_PREVIEW",
                model_name="Attachment",
                object_id=attachment.id,
                after_state={"filename": attachment.original_filename, "document": doc.internal_number},
            )
        else:
            AuditService.log_audit(
                actor=request.user,
                action="ATTACHMENT_DOWNLOAD",
                model_name="Attachment",
                object_id=attachment.id,
                after_state={"filename": attachment.original_filename},
            )

    response = FileResponse(
        open(integrity["vault_path"], "rb"),
        content_type=attachment.mime_type or "application/octet-stream",
        as_attachment=not inline,
        filename=attachment.original_filename,
    )
    if inline and mime_lower == "image/svg+xml":
        response["Content-Security-Policy"] = "sandbox"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store, private"
    return response


@login_required
def document_export_pdf(request, doc_id: int):
    """تصدير بطاقة المستند ومرفقاته إلى ملف PDF مؤسسي للطباعة المباشرة."""
    doc = get_object_or_404(
        Document.objects.select_related("doc_type", "confidentiality", "created_by")
        .prefetch_related("versions__attachments", "subjectdocumentlink_set__subject"),
        id=doc_id,
    )
    if not PermissionService.can_view_document(request.user, doc):
        raise PermissionDenied("غير مصرح لك بتصدير هذا المستند.")

    versions_lines = []
    for ver in doc.versions.all():
        att_names = ", ".join(a.original_filename for a in ver.attachments.all()) or "No attachments"
        versions_lines.append(
            f"v{ver.version_number} | Approved: {'Yes' if ver.is_approved else 'No'} | Files: {att_names}"
        )
    linked_lines = [
        f"{lnk.subject.internal_number}: {lnk.subject.title}"
        for lnk in doc.subjectdocumentlink_set.all()
        if PermissionService.can_view_subject(request.user, lnk.subject)
    ]

    pdf_bytes = build_institutional_pdf_bytes(
        title=f"Document {doc.internal_number} - {doc.title}",
        subtitle=f"Type: {doc.doc_type.name} | Confidentiality: {doc.confidentiality.name}",
        metadata_rows=[
            ("Internal Number", doc.internal_number),
            ("External Ref", doc.external_in_out_number or "-"),
            ("Source Type", doc.get_source_type_display()),
            ("Sender Entity", doc.sender_entity or "-"),
            ("Receiver Entity", doc.receiver_entity or "-"),
            ("Document Date", str(doc.document_date or doc.created_at.date())),
            ("Created By", str(doc.created_by)),
        ],
        sections=[
            {"heading": "Document Summary", "lines": [doc.summary or "-"]},
            {"heading": "Versions & Attachments", "lines": versions_lines or ["-"]},
            {"heading": "Linked Subjects", "lines": linked_lines or ["-"]},
        ],
    )
    AuditService.log_audit(
        actor=request.user,
        action="DOCUMENT_EXPORT_PDF",
        model_name="Document",
        object_id=doc.id,
        after_state={"internal_number": doc.internal_number},
    )
    return pdf_http_response(pdf_bytes, f"document_{doc.internal_number}.pdf", inline=request.GET.get("inline") == "1")
