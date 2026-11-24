import json
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.core.paginator import Paginator
from .guidance import build_dashboard_guidance
from django.db import IntegrityError, connection
from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from accounts.services import PermissionService
from audit.services import AuditService
from committees.models import CommitteeAgendaItem
from decisions.models import Decision
from documents.models import Attachment, Document
from organization.models import OrgUnit, Sector
from subjects.models import Subject
from workflow.models import Referral, ReferralRecipient, Task
from .models import (
    ConfidentialityLevel,
    DocumentType,
    MemoRecipientRef,
    MemoTypeRef,
    PriorityLevel,
    RetentionPolicy,
    SuspensionReason,
    TransactionType,
)


def _filter_visible_documents(docs_qs, user):
    """تصفية المستندات بدقة وفق الطبقة المركزية لصلاحيات المستندات وعزل القطاعات."""
    return [doc for doc in docs_qs if PermissionService.can_view_document(user, doc)]


@login_required
def dashboard(request):
    """صندوق البريد الإداري المطابق لـ Gmail مع التبويبات الـ 4 وتطبيق طبقة الصلاحيات المنطقية والأداء العالي."""
    folder = request.GET.get("folder", "inbox")
    tab = request.GET.get("tab", "primary")
    q = request.GET.get("q", "").strip()

    # جلب المرفق الأول باستخدام Subquery لتفادي الحلقات الثلاثية N+1
    first_att_name_subq = Subquery(
        Attachment.objects.filter(
            document_version__document__subjectdocumentlink__subject=OuterRef("pk")
        ).values("original_filename")[:1]
    )
    first_att_id_subq = Subquery(
        Attachment.objects.filter(
            document_version__document__subjectdocumentlink__subject=OuterRef("pk")
        ).values("id")[:1]
    )
    first_att_mime_subq = Subquery(
        Attachment.objects.filter(
            document_version__document__subjectdocumentlink__subject=OuterRef("pk")
        ).values("mime_type")[:1]
    )

    all_subjects_qs = Subject.objects.select_related(
        "transaction_type", "sector", "org_unit", "confidentiality", "priority", "current_owner", "created_by"
    ).annotate(
        doc_count=Count("documents", distinct=True),
        first_att_id=first_att_id_subq,
        first_att_name=first_att_name_subq,
        first_att_mime=first_att_mime_subq,
    ).prefetch_related("referrals__referred_by")

    if q:
        all_subjects_qs = all_subjects_qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(internal_number__icontains=q)
            | Q(org_unit__name__icontains=q)
        ).distinct()

    visible_subjects = list(PermissionService.filter_visible_subjects(all_subjects_qs, request.user))
    today = timezone.localdate()

    # معرفة الإحالات المعلقة والمكلفة للمستخدم الحالي دفعة واحدة دون تكرار الاستعلام
    active_delegations = PermissionService.get_active_delegations_for_delegate(request.user)
    delegator_ids = {
        d.delegator_id for d in active_delegations
        if "REFERRAL_CREATE" in (d.allowed_actions or [])
    }
    user_unit = getattr(request.user, "current_unit", None)
    unit_filter = Q(target_unit=user_unit, target_user__isnull=True) if user_unit else Q(pk__in=[])

    pending_recs = ReferralRecipient.objects.filter(
        Q(target_user=request.user) | Q(target_user_id__in=delegator_ids) | unit_filter,
        status=ReferralRecipient.RecipientStatus.PENDING,
        is_active_step=True,
    ).select_related("referral")
    pending_map = {rec.referral.subject_id: rec.id for rec in pending_recs}

    active_recip_subject_ids = set(
        ReferralRecipient.objects.filter(
            Q(target_user=request.user) | Q(target_user_id__in=delegator_ids) | unit_filter,
            is_active_step=True,
        ).exclude(referral__purpose=Referral.Purpose.FOR_INFO).values_list("referral__subject_id", flat=True)
    )
    is_admin = bool(request.user.is_superuser or getattr(request.user, "is_system_admin", False))

    for s in visible_subjects:
        s.pending_ref_id = pending_map.get(s.id)
        s.has_pending_ref = s.pending_ref_id is not None
        s.can_act = is_admin or (s.current_owner_id == request.user.id) or (s.id in active_recip_subject_ids) or (s.current_owner_id in delegator_ids)
        refs = list(s.referrals.all())
        s.sender_label = str(refs[0].referred_by) if refs else str(s.current_owner)
        if getattr(s, "first_att_id", None):
            s.first_att = {
                "id": s.first_att_id,
                "original_filename": s.first_att_name or "ملف",
                "mime_type": s.first_att_mime or "",
            }
        else:
            s.first_att = None

    active_subjects = [s for s in visible_subjects if s.status != Subject.Status.CLOSED]
    inbox_subjects = [s for s in active_subjects if s.can_act or s.has_pending_ref]
    readonly_subjects = [s for s in active_subjects if not s.can_act and not s.has_pending_ref]
    pending_subjects = [s for s in active_subjects if s.has_pending_ref]
    overdue_subjects = [s for s in active_subjects if s.is_overdue]
    sent_subjects = [
        s for s in visible_subjects
        if not s.can_act and any(r.referred_by_id == request.user.id for r in s.referrals.all())
    ]
    closed_subjects = [s for s in visible_subjects if s.status == Subject.Status.CLOSED]

    # المهام والقرارات المضمنة داخل تبويب "المهام والقرارات"
    tasks_qs = (
        Task.objects.select_related("subject__confidentiality", "assigned_to", "priority")
        .exclude(status__in=[Task.TaskStatus.COMPLETED, Task.TaskStatus.CANCELLED])
        .order_by("-assigned_at")
    )
    if not request.user.is_superuser:
        tasks_qs = tasks_qs.filter(assigned_to=request.user)
    tasks_list = [
        t for t in tasks_qs[:60]
        if t.subject_id and PermissionService.can_view_subject(request.user, t.subject)
    ]

    visible_subject_ids = [s.id for s in visible_subjects]
    decisions_list = list(
        Decision.objects.filter(subject_id__in=visible_subject_ids)
        .select_related("subject", "created_by")
        .order_by("-created_at")[:40]
    )

    if folder == "inbox":
        if tab == "primary":
            all_displayed = inbox_subjects if (inbox_subjects or request.user.is_superuser) else active_subjects
        elif tab == "readonly":
            all_displayed = readonly_subjects
        elif tab == "overdue":
            all_displayed = overdue_subjects
        elif tab == "tasks":
            all_displayed = []
        else:
            all_displayed = active_subjects
    elif folder == "pending":
        all_displayed = pending_subjects
    elif folder == "overdue":
        all_displayed = overdue_subjects
    elif folder == "sent":
        all_displayed = sent_subjects
    elif folder == "archive":
        all_displayed = closed_subjects
    else:
        all_displayed = visible_subjects

    # تطبيق التصفح بالصفحات Paginator بمعدل 25 موضوعاً بالصفحة
    paginator = Paginator(all_displayed, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "core/dashboard.html",
        {
            "folder": folder,
            "tab": tab,
            "q": q,
            "displayed_subjects": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "total_count": paginator.count,
            "tasks_list": tasks_list,
            "decisions_list": decisions_list,
            "tab_counts": {
                "primary": len(inbox_subjects),
                "readonly": len(readonly_subjects),
                "overdue": len(overdue_subjects),
                "tasks": len(tasks_list),
            },
            "guide": build_dashboard_guidance({
                "primary": len(inbox_subjects),
                "readonly": len(readonly_subjects),
                "overdue": len(overdue_subjects),
                "tasks": len(tasks_list),
            }),
            "today": today,
            "is_inbox_page": True,
        },
    )


@login_required
def archive_quick_search(request):
    """
    البحث المتقدم في أرشيف المستندات والموضوعات (بالتاريخ، جهة الصدور، نوع المستند، السرية، والبحث النصي).
    يلتزم التزاماً صارماً بصلاحيات المستخدم والسرية الفائقة.
    """
    q = request.GET.get("q", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    source = request.GET.get("source", "").strip()
    doc_type_id = request.GET.get("doc_type", "").strip()
    conf_id = request.GET.get("confidentiality", "").strip()
    sector_id = request.GET.get("sector", "").strip()

    docs_qs = Document.objects.select_related(
        "doc_type", "confidentiality", "created_by__employee__current_unit__sector"
    ).prefetch_related("subjects", "versions__attachments")

    subj_qs = Subject.objects.select_related(
        "transaction_type", "sector", "org_unit", "confidentiality", "current_owner"
    )

    if q:
        docs_qs = docs_qs.filter(
            Q(title__icontains=q)
            | Q(summary__icontains=q)
            | Q(internal_number__icontains=q)
            | Q(external_in_out_number__icontains=q)
            | Q(sender_entity__icontains=q)
            | Q(receiver_entity__icontains=q)
        )
        subj_qs = subj_qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(internal_number__icontains=q)
            | Q(keywords__icontains=q)
            | Q(external_source__icontains=q)
            | Q(applicant_name__icontains=q)
        )

    if date_from:
        docs_qs = docs_qs.filter(Q(document_date__gte=date_from) | Q(document_date__isnull=True, created_at__date__gte=date_from))
        subj_qs = subj_qs.filter(created_at__date__gte=date_from)
    if date_to:
        docs_qs = docs_qs.filter(Q(document_date__lte=date_to) | Q(document_date__isnull=True, created_at__date__lte=date_to))
        subj_qs = subj_qs.filter(created_at__date__lte=date_to)
    if source:
        docs_qs = docs_qs.filter(
            Q(sender_entity__icontains=source)
            | Q(receiver_entity__icontains=source)
            | Q(subjects__external_source__icontains=source)
            | Q(subjects__applicant_name__icontains=source)
        )
        subj_qs = subj_qs.filter(
            Q(external_source__icontains=source)
            | Q(applicant_name__icontains=source)
            | Q(documents__sender_entity__icontains=source)
        )
    if doc_type_id and doc_type_id.isdigit():
        docs_qs = docs_qs.filter(doc_type_id=int(doc_type_id))
        subj_qs = subj_qs.filter(documents__doc_type_id=int(doc_type_id))
    if conf_id and conf_id.isdigit():
        docs_qs = docs_qs.filter(confidentiality_id=int(conf_id))
        subj_qs = subj_qs.filter(confidentiality_id=int(conf_id))
    if sector_id and sector_id.isdigit():
        docs_qs = docs_qs.filter(
            Q(subjects__sector_id=int(sector_id)) | Q(created_by__employee__current_unit__sector_id=int(sector_id))
        )
        subj_qs = subj_qs.filter(sector_id=int(sector_id))

    has_filters = any([q, date_from, date_to, source, doc_type_id, conf_id, sector_id])
    docs_qs = docs_qs.distinct().order_by("-created_at")
    if not has_filters:
        docs_qs = docs_qs[:25]
    else:
        # تحديد سقف أقصى للمطابقات في الذاكرة لمنع تجميد الخادم في الأرشيفات الضخمة
        docs_qs = docs_qs[:300]

    doc_results_all = _filter_visible_documents(docs_qs, request.user)
    visible_subjects_qs = PermissionService.filter_visible_subjects(subj_qs.distinct(), request.user)
    subject_results_all = list(visible_subjects_qs[:300]) if has_filters else []

    doc_page_number = request.GET.get("page", 1)
    doc_paginator = Paginator(doc_results_all, 25)
    doc_page_obj = doc_paginator.get_page(doc_page_number)

    return render(
        request,
        "core/archive_search.html",
        {
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "source": source,
            "doc_type_id": doc_type_id,
            "conf_id": conf_id,
            "sector_id": sector_id,
            "has_filters": has_filters,
            "doc_types": DocumentType.objects.filter(is_active=True),
            "confidentialities": ConfidentialityLevel.objects.filter(is_active=True),
            "sectors": Sector.objects.filter(is_active=True),
            "doc_results": doc_page_obj.object_list,
            "doc_page_obj": doc_page_obj,
            "doc_paginator": doc_paginator,
            "subject_results": subject_results_all[:50],
        },
    )


@login_required
def user_guide_view(request):
    """دليل الاستخدام المصور المبسط خطوة بخطوة للمبتدئين."""
    return render(request, "core/user_guide.html")


@login_required
def database_admin_view(request):
    """
    شاشة إدارة قواعد البيانات من داخل التطبيق — متاحة حصرياً للـ Superuser فقط.
    """
    if not request.user.is_superuser:
        AuditService.log_audit(
            actor=request.user,
            action="UNAUTHORIZED_DB_ADMIN_ACCESS",
            model_name="DatabaseAdmin",
            object_id=0,
            outcome="DENIED",
        )
        raise PermissionDenied("هذه الشاشة مخصصة لمدير النظام الأعلى (Superuser) فقط.")

    app_labels = {
        "core", "organization", "accounts", "subjects", "documents",
        "workflow", "committees", "decisions", "audit", "notifications", "chat",
    }
    models_map = {}
    tables_summary = []
    for model in apps.get_models():
        if model._meta.app_label in app_labels:
            key = f"{model._meta.app_label}.{model.__name__}"
            models_map[key] = model
            tables_summary.append({
                "key": key,
                "app_label": model._meta.app_label,
                "model_name": model.__name__,
                "verbose_name": str(model._meta.verbose_name_plural),
                "db_table": model._meta.db_table,
                "count": model.objects.count(),
            })
    tables_summary.sort(key=lambda x: (x["app_label"], x["model_name"]))

    selected_key = request.GET.get("table") or request.POST.get("table") or "subjects.Subject"
    selected_model = models_map.get(selected_key) or Subject
    selected_key = f"{selected_model._meta.app_label}.{selected_model.__name__}"

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "export_json":
            snapshot = {}
            for key, m in models_map.items():
                snapshot[key] = list(m.objects.values())
            AuditService.log_audit(
                actor=request.user,
                action="DB_JSON_EXPORT",
                model_name="DatabaseAdmin",
                object_id=0,
                after_state={"tables_exported": len(snapshot)},
            )
            payload = json.dumps(snapshot, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)
            resp = HttpResponse(payload, content_type="application/json; charset=utf-8")
            resp["Content-Disposition"] = 'attachment; filename="correspondence_db_backup.json"'
            return resp

        if action == "add_ref_tx":
            code = request.POST.get("code", "").strip().upper()
            name = request.POST.get("name", "").strip()
            if code and name:
                TransactionType.objects.get_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "requires_decision": request.POST.get("requires_decision") == "on",
                        "requires_committee": request.POST.get("requires_committee") == "on",
                    },
                )
                AuditService.log_audit(
                    actor=request.user,
                    action="DB_ADMIN_ADD_TX_TYPE",
                    model_name="TransactionType",
                    object_id=0,
                    after_state={"code": code, "name": name},
                )
                messages.success(request, f"تمت إضافة نوع المعاملة ({name}) بنجاح.")
            return redirect(f"{request.path}?table=core.TransactionType")

        if action == "delete_ref_row":
            row_id = request.POST.get("row_id")
            if selected_key in ("core.TransactionType", "core.DocumentType", "core.SuspensionReason"):
                try:
                    selected_model.objects.filter(id=row_id).delete()
                    AuditService.log_audit(
                        actor=request.user,
                        action="DB_ADMIN_DELETE_ROW",
                        model_name=selected_key,
                        object_id=int(row_id or 0),
                    )
                    messages.info(request, "تم حذف السجل المرجعي المحدد.")
                except Exception as exc:
                    messages.error(request, f"تعذر حذف السجل لارتباطه ببيانات أخرى: {exc}")
            return redirect(f"{request.path}?table={selected_key}")

    integrity_result = "غير متاح لهذا المحرك"
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA integrity_check;")
            integrity_result = cursor.fetchone()[0]

    fields = [f.name for f in selected_model._meta.fields[:8]]
    rows = list(selected_model.objects.order_by("-id").values(*fields)[:30])
    formatted_rows = [
        {"id": r.get("id"), "cells": [r.get(f) for f in fields]}
        for r in rows
    ]

    return render(
        request,
        "core/db_admin.html",
        {
            "db_vendor": connection.vendor,
            "integrity_result": integrity_result,
            "tables_summary": tables_summary,
            "selected_key": selected_key,
            "selected_verbose": str(selected_model._meta.verbose_name_plural),
            "fields": fields,
            "formatted_rows": formatted_rows,
            "can_edit_ref": selected_key in ("core.TransactionType", "core.DocumentType", "core.SuspensionReason"),
        },
    )


@login_required
def advanced_search(request):
    """
    محرك البحث المتقدم:
    يدعم البحث برقم الموضوع، رقم المستند الداخلي، رقم الصادر/الوارد، العنوان،
    الملخص، نوع المعاملة، الجهة الواردة، الوحدة، السرية، التواريخ، والكلمات المفتاحية.
    لا يكشف أي موضوع سري للمستخدم غير المصرح له.
    """
    q_text = request.GET.get("q", "").strip()
    tx_type_id = request.GET.get("transaction_type")
    doc_type_id = request.GET.get("doc_type")
    source_filter = request.GET.get("source", "").strip()
    sector_id = request.GET.get("sector")
    unit_id = request.GET.get("org_unit")
    status = request.GET.get("status")
    conf_id = request.GET.get("confidentiality")
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")

    qs = Subject.objects.select_related(
        "transaction_type", "sector", "org_unit", "confidentiality", "priority", "current_owner"
    )
    if q_text:
        qs = qs.filter(
            Q(internal_number__icontains=q_text)
            | Q(title__icontains=q_text)
            | Q(description__icontains=q_text)
            | Q(keywords__icontains=q_text)
            | Q(applicant_name__icontains=q_text)
            | Q(external_source__icontains=q_text)
            | Q(documents__internal_number__icontains=q_text)
            | Q(documents__external_in_out_number__icontains=q_text)
            | Q(documents__title__icontains=q_text)
            | Q(documents__summary__icontains=q_text)
        ).distinct()

    if tx_type_id:
        qs = qs.filter(transaction_type_id=tx_type_id)
    if doc_type_id and str(doc_type_id).isdigit():
        qs = qs.filter(documents__doc_type_id=int(doc_type_id)).distinct()
    if source_filter:
        qs = qs.filter(
            Q(external_source__icontains=source_filter)
            | Q(applicant_name__icontains=source_filter)
            | Q(documents__sender_entity__icontains=source_filter)
            | Q(documents__receiver_entity__icontains=source_filter)
        ).distinct()
    if sector_id:
        qs = qs.filter(sector_id=sector_id)
    if unit_id:
        qs = qs.filter(org_unit_id=unit_id)
    if status:
        qs = qs.filter(status=status)
    if conf_id:
        qs = qs.filter(confidentiality_id=conf_id)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    results_qs = PermissionService.filter_visible_subjects(qs, request.user)
    paginator = Paginator(results_qs, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "core/search.html",
        {
            "results": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "total_count": paginator.count,
            "q_text": q_text,
            "transaction_types": TransactionType.objects.all(),
            "doc_types": DocumentType.objects.filter(is_active=True),
            "sectors": Sector.objects.all(),
            "org_units": OrgUnit.objects.all(),
            "confidentialities": ConfidentialityLevel.objects.all(),
            "status_choices": Subject.Status.choices,
            "filters": request.GET,
        },
    )


@login_required
def system_settings(request):
    """إدارة القوائم المرجعية للنظام (أنواع المعاملات، المذكرات، الجهات، السرية، الأولوية، المستندات، أسباب التعليق)."""
    role_codes = PermissionService.get_effective_role_codes(request.user)
    if not (
        PermissionService.user_has_permission(request.user, "SYSTEM_SETTINGS")
        or bool(role_codes & {"CHAIRMAN", "SECTOR_HEAD"})
    ):
        raise PermissionDenied("ليس لديك صلاحية إدارة إعدادات النظام.")

    active_tab = request.GET.get("tab") or request.POST.get("list_type") or "transaction_types"
    valid_tabs = {
        "transaction_types",
        "memo_types",
        "memo_directed_targets",
        "confidentiality_levels",
        "priority_levels",
        "doc_types",
        "suspension_reasons",
    }
    if active_tab not in valid_tabs:
        active_tab = "transaction_types"

    model_by_tab = {
        "transaction_types": TransactionType,
        "memo_types": MemoTypeRef,
        "memo_directed_targets": MemoRecipientRef,
        "confidentiality_levels": ConfidentialityLevel,
        "priority_levels": PriorityLevel,
        "doc_types": DocumentType,
        "suspension_reasons": SuspensionReason,
    }

    if request.method == "POST":
        import uuid
        legacy_action = request.POST.get("action")
        list_type = request.POST.get("list_type", active_tab)
        op = request.POST.get("op", "")

        # دعم الأفعال القديمة للتوافق الخلفي الكامل
        if legacy_action == "add_tx_type":
            list_type, op = "transaction_types", "add"
        elif legacy_action == "add_doc_type":
            list_type, op = "doc_types", "add"
        elif legacy_action == "add_suspension_reason":
            list_type, op = "suspension_reasons", "add"

        target_model = model_by_tab.get(list_type)
        if target_model is not None and op in {"add", "edit", "delete"}:
            name_val = request.POST.get("name", "").strip()
            code_val = request.POST.get("code", "").strip().upper()
            item_id = request.POST.get("item_id")

            try:
                if op == "add":
                    if not name_val:
                        messages.error(request, "المسمى مطلوب.")
                    else:
                        final_code = code_val or f"REF_{uuid.uuid4().hex[:6].upper()}"
                        defaults = {"name": name_val, "is_active": True}
                        if list_type == "transaction_types":
                            defaults.update({
                                "requires_committee": request.POST.get("requires_committee") == "on",
                                "requires_decision": request.POST.get("requires_decision") == "on",
                                "requires_execution_proof": request.POST.get("requires_execution_proof") == "on",
                            })
                        elif list_type == "confidentiality_levels":
                            rank_num = max(1, min(3, int(request.POST.get("rank") or 1)))
                            defaults.update({"rank": rank_num, "overrides_hierarchy": rank_num == 3})
                        elif list_type == "priority_levels":
                            sla = max(1, min(90, int(request.POST.get("sla_days") or 5)))
                            defaults.update({"sla_days": sla, "rank": int(request.POST.get("rank") or 2)})
                        target_model.objects.get_or_create(code=final_code, defaults=defaults)
                        messages.success(request, f"تمت إضافة «{name_val}» إلى القائمة المرجعية بنجاح.")

                elif op == "edit" and item_id:
                    obj = target_model.objects.filter(id=item_id).first()
                    if obj and name_val:
                        obj.name = name_val
                        if code_val:
                            obj.code = code_val
                        if list_type == "transaction_types":
                            obj.requires_committee = request.POST.get("requires_committee") == "on"
                            obj.requires_decision = request.POST.get("requires_decision") == "on"
                            obj.requires_execution_proof = request.POST.get("requires_execution_proof") == "on"
                        elif list_type == "confidentiality_levels":
                            rank_num = max(1, min(3, int(request.POST.get("rank") or obj.rank or 1)))
                            obj.rank = rank_num
                            obj.overrides_hierarchy = rank_num == 3
                        elif list_type == "priority_levels":
                            obj.sla_days = max(1, min(90, int(request.POST.get("sla_days") or obj.sla_days or 5)))
                        obj.save()
                        messages.success(request, f"تم تعديل العنصر «{obj.name}» بنجاح.")

                elif op == "delete" and item_id:
                    obj = target_model.objects.filter(id=item_id).first()
                    if obj:
                        label = obj.name
                        obj.delete()
                        messages.success(request, f"تم حذف العنصر «{label}» من القائمة المرجعية.")
            except (ProtectedError, IntegrityError):
                messages.error(request, "لا يمكن حذف أو تعديل هذا العنصر لارتباطه بمعاملات أو سجلات قائمة.")

        return redirect(f"{reverse('core:settings')}?tab={list_type}")

    return render(
        request,
        "core/settings.html",
        {
            "active_tab": active_tab,
            "transaction_types": TransactionType.objects.all(),
            "memo_types_list": MemoTypeRef.objects.all(),
            "memo_targets_list": MemoRecipientRef.objects.all(),
            "doc_types": DocumentType.objects.all(),
            "confidentialities": ConfidentialityLevel.objects.all(),
            "priorities": PriorityLevel.objects.all(),
            "suspension_reasons": SuspensionReason.objects.all(),
            "retention_policies": RetentionPolicy.objects.all(),
        },
    )
