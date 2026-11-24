"""
خدمات التقارير الإدارية والتشغيلية الاثني عشر مع:
1. الفحص الصارم عبر الطبقة المركزية accounts/permissions_layer.py وعزل القطاعات والوحدات.
2. رفض أي محاولة تلاعب بمرشح القطاع خارج نطاق المستخدم عبر PermissionDenied.
3. حساب متوسط زمن الإنجاز من أحداث الإنشاء والإغلاق الموثوقة (ActivityLog / SubjectStatusHistory / Subject.closed_at)
   مع استبعاد الموضوعات غير المغلقة وتوثيق الحالات الناقصة أو المكررة بدقة.
4. عدم اختلاق أي تواريخ افتراضية وهمية.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from accounts.permissions_layer import CorrespondenceAccessPolicy
from accounts.services import PermissionService
from audit.models import ActivityLog, AuditLog
from committees.models import CommitteeAgendaItem
from core.models import TransactionType
from decisions.models import Decision, DecisionExecutionItem
from documents.models import Attachment, Document, SubjectDocumentLink
from organization.models import OrgUnit, Sector
from subjects.models import Subject, SubjectStatusHistory, SubjectSuspension
from workflow.models import Referral, ReferralRecipient, Task


@dataclass(frozen=True)
class ReportDefinition:
    slug: str
    number: int
    title: str
    subtitle: str
    icon: str
    category: str
    supports_tx_filter: bool = True
    restricted_audit: bool = False


REPORT_DEFINITIONS: tuple[ReportDefinition, ...] = (
    ReportDefinition(
        slug="documents-summary",
        number=1,
        title="إجمالي المستندات الواردة والصادرة مع مقارنة الفترات",
        subtitle="حصر المستندات الواردة والصادرة والداخلية ومقارنة الأداء مع الفترة السابقة المماثلة.",
        icon="📄",
        category="المستندات والأرشفة",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="documents-by-org",
        number=2,
        title="المستندات حسب القطاع والإدارة والقسم",
        subtitle="توزيع المستندات المرئية وفق الهيكل التنظيمي (القطاع / الإدارة العامة / القسم).",
        icon="🏢",
        category="المستندات والأرشفة",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="subjects-status",
        number=3,
        title="الموضوعات المفتوحة والمغلقة",
        subtitle="بيان حالة الموضوعات الجارية والمغلقة ومعدل الإغلاق الكلي في نطاقك.",
        icon="📂",
        category="الموضوعات",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="suspended-subjects",
        number=4,
        title="الموضوعات المعلقة مع أسباب التعليق",
        subtitle="متابعة حالات التعليق والاستيفاء المسجلة في SubjectSuspension ومهلها.",
        icon="⏸️",
        category="الموضوعات",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="overdue-tasks",
        number=5,
        title="المهام المتأخرة",
        subtitle="المهام التي تجاوزت تاريخ الاستحقاق (due_date) ولم تكتمل أو تُلغَ حتى الآن.",
        icon="⏰",
        category="المهام والأداء",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="avg-completion-time",
        number=6,
        title="متوسط زمن إنجاز المعاملات",
        subtitle="قياس المدة الفعلية من حدث إنشاء الموضوع حتى حدث الإغلاق الموثوق للموضوعات المغلقة فقط.",
        icon="⏱️",
        category="المهام والأداء",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="referrals-by-unit",
        number=7,
        title="عدد الإحالات لكل إدارة",
        subtitle="توزيع الإحالات الصادرة والواردة لكل وحدة تنظيمية وحالات الاستلام والرد.",
        icon="🔀",
        category="سير العمل والإحالات",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="employee-workload",
        number=8,
        title="حجم العمل لكل موظف",
        subtitle="إجمالي المهام المسندة والمكتملة والمتأخرة ونسبة الإنجاز لكل موظف في نطاقك.",
        icon="👤",
        category="المهام والأداء",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="issued-decisions",
        number=9,
        title="القرارات الصادرة",
        subtitle="حصر القرارات الإدارية المعتمدة والصادرة وتواريخ إصدارها وجهات الاعتماد.",
        icon="⚖️",
        category="القرارات واللجان",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="incomplete-decisions",
        number=10,
        title="القرارات التي لم يكتمل تنفيذها",
        subtitle="متابعة بنود تنفيذ القرارات غير المكتملة مباشرة من DecisionExecutionItem.",
        icon="📌",
        category="القرارات واللجان",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="committee-subjects",
        number=11,
        title="الموضوعات المعروضة على اللجان",
        subtitle="بنود جداول أعمال اللجان وتوصياتها ونتائج العرض المسجلة في CommitteeAgendaItem.",
        icon="🏛️",
        category="القرارات واللجان",
        supports_tx_filter=True,
    ),
    ReportDefinition(
        slug="confidential-audit",
        number=12,
        title="حركة الاطلاع على المستندات السرية",
        subtitle="رصد عمليات المعاينة والتنزيل ومحاولة الوصول للمستندات السرية من AuditLog.",
        icon="🔒",
        category="الأمان والتدقيق",
        supports_tx_filter=False,
        restricted_audit=True,
    ),
)

REPORT_MAP: dict[str, ReportDefinition] = {r.slug: r for r in REPORT_DEFINITIONS}


@dataclass
class ResolvedFilters:
    date_from: date | None
    date_to: date | None
    sector: Sector | None
    transaction_type: TransactionType | None
    allowed_sectors: list[Sector]
    transaction_types: list[TransactionType]
    is_org_wide: bool
    allowed_sector_ids: set[int]


def _parse_date(raw: str | None, field_label: str) -> date | None:
    if not raw or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValidationError(f"صيغة {field_label} غير صالحة (المتوقع YYYY-MM-DD).") from exc


def _to_aware_start(d: date):
    return timezone.make_aware(datetime.combine(d, time.min), timezone.get_current_timezone())


def _to_aware_end(d: date):
    return timezone.make_aware(datetime.combine(d, time.max), timezone.get_current_timezone())


def get_allowed_sectors_for_user(user) -> tuple[bool, set[int], list[Sector]]:
    boundaries = CorrespondenceAccessPolicy.get_user_scope_boundaries(user)
    is_org_wide = bool(boundaries["is_org_wide"])
    allowed_sector_ids = set(boundaries["allowed_sector_ids"])
    if is_org_wide:
        sectors = list(Sector.objects.filter(is_active=True).order_by("name"))
        allowed_sector_ids = {s.id for s in sectors}
    else:
        sectors = list(Sector.objects.filter(id__in=allowed_sector_ids, is_active=True).order_by("name"))
    return is_org_wide, allowed_sector_ids, sectors


def resolve_report_filters(user, params) -> ResolvedFilters:
    if not PermissionService.user_has_permission(user, "REPORTS_VIEW"):
        raise PermissionDenied("ليس لديك صلاحية الاطلاع على التقارير.")

    is_org_wide, allowed_sector_ids, allowed_sectors = get_allowed_sectors_for_user(user)

    date_from = _parse_date(params.get("date_from"), "تاريخ البداية")
    date_to = _parse_date(params.get("date_to"), "تاريخ النهاية")
    if date_from and date_to and date_from > date_to:
        raise ValidationError("تاريخ البداية لا يمكن أن يكون بعد تاريخ النهاية.")

    raw_sector = (params.get("sector") or "").strip()
    selected_sector: Sector | None = None
    if raw_sector:
        try:
            sector_id = int(raw_sector)
        except ValueError as exc:
            raise ValidationError("معرّف القطاع غير صالح.") from exc
        selected_sector = Sector.objects.filter(id=sector_id, is_active=True).first()
        if selected_sector is None:
            raise ValidationError("القطاع المحدد غير موجود.")
        if not is_org_wide and selected_sector.id not in allowed_sector_ids:
            raise PermissionDenied("غير مصرح لك بالاطلاع على بيانات قطاع خارج نطاق صلاحياتك.")

    raw_tx = (params.get("transaction_type") or "").strip()
    selected_tx: TransactionType | None = None
    if raw_tx:
        try:
            tx_id = int(raw_tx)
        except ValueError as exc:
            raise ValidationError("معرّف نوع المعاملة غير صالح.") from exc
        selected_tx = TransactionType.objects.filter(id=tx_id, is_active=True).first()
        if selected_tx is None:
            raise ValidationError("نوع المعاملة المحدد غير موجود.")

    tx_qs = TransactionType.objects.filter(is_active=True)
    if not is_org_wide and allowed_sector_ids:
        tx_qs = tx_qs.filter(Q(sector_id__in=allowed_sector_ids) | Q(sector__isnull=True))

    return ResolvedFilters(
        date_from=date_from,
        date_to=date_to,
        sector=selected_sector,
        transaction_type=selected_tx,
        allowed_sectors=allowed_sectors,
        transaction_types=list(tx_qs.order_by("name")),
        is_org_wide=is_org_wide,
        allowed_sector_ids=allowed_sector_ids,
    )


def can_view_confidential_audit_report(user) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or user.is_system_admin:
        return True
    if PermissionService.user_has_permission(user, "AUDIT_VIEW"):
        return True
    return any(
        a.role.can_view_confidential or a.role.can_view_top_secret
        for a in CorrespondenceAccessPolicy.get_active_assignments(user)
    )


def _scoped_subjects_qs(user, filters: ResolvedFilters, *, apply_created_dates: bool = True):
    qs = Subject.objects.select_related(
        "transaction_type",
        "sector",
        "org_unit",
        "org_unit__parent",
        "org_unit__unit_type",
        "confidentiality",
        "priority",
        "current_owner",
        "created_by",
        "closed_by",
    )
    if filters.sector is not None:
        qs = qs.filter(sector=filters.sector)
    if filters.transaction_type is not None:
        qs = qs.filter(transaction_type=filters.transaction_type)
    if apply_created_dates:
        if filters.date_from:
            qs = qs.filter(created_at__gte=_to_aware_start(filters.date_from))
        if filters.date_to:
            qs = qs.filter(created_at__lte=_to_aware_end(filters.date_to))
    return PermissionService.filter_visible_subjects(qs, user)


def _visible_documents(user, filters: ResolvedFilters, *, date_from: date | None = None, date_to: date | None = None):
    docs_qs = Document.objects.select_related(
        "doc_type",
        "confidentiality",
        "created_by",
        "created_by__employee__current_unit__sector",
        "created_by__employee__current_unit__unit_type",
        "created_by__employee__current_unit__parent",
    ).prefetch_related(
        "subjectdocumentlink_set__subject__sector",
        "subjectdocumentlink_set__subject__org_unit__unit_type",
        "subjectdocumentlink_set__subject__org_unit__parent",
        "subjectdocumentlink_set__subject__transaction_type",
    )
    if date_from:
        docs_qs = docs_qs.filter(created_at__gte=_to_aware_start(date_from))
    if date_to:
        docs_qs = docs_qs.filter(created_at__lte=_to_aware_end(date_to))

    result = []
    for doc in docs_qs:
        if not PermissionService.can_view_document(user, doc):
            continue
        links = list(doc.subjectdocumentlink_set.all())
        visible_links = [lk for lk in links if PermissionService.can_view_subject(user, lk.subject)]
        primary_link = next((lk for lk in visible_links if lk.is_primary_subject), visible_links[0] if visible_links else None)
        primary_subject = primary_link.subject if primary_link else None

        doc_sector = (
            primary_subject.sector
            if primary_subject
            else (doc.created_by.current_sector if doc.created_by else None)
        )
        doc_unit = (
            primary_subject.org_unit
            if primary_subject
            else (doc.created_by.current_unit if doc.created_by else None)
        )
        doc_tx_id = primary_subject.transaction_type_id if primary_subject else None

        if filters.sector is not None and (doc_sector is None or doc_sector.id != filters.sector.id):
            continue
        if filters.transaction_type is not None and doc_tx_id != filters.transaction_type.id:
            continue
        if not filters.is_org_wide and doc_sector is not None and doc_sector.id not in filters.allowed_sector_ids:
            continue

        result.append((doc, primary_subject, doc_sector, doc_unit))
    return result


def _resolve_general_directorate_and_section(unit: OrgUnit | None) -> tuple[str, str]:
    if unit is None:
        return "غير محدد", "غير محدد"
    section_name = unit.name
    gd_name = "—"
    cur = unit
    visited = set()
    while cur is not None and cur.id not in visited:
        visited.add(cur.id)
        if getattr(cur.unit_type, "code", "") == "GENERAL_DIR":
            gd_name = cur.name
            break
        cur = cur.parent
    if gd_name == "—" and unit.parent:
        gd_name = unit.parent.name
    return gd_name, section_name


def _pct_change(current: int, previous: int) -> str:
    if previous == 0:
        return "جديد (∞)" if current > 0 else "0%"
    diff = ((current - previous) / previous) * 100.0
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.1f}%"


def _build_documents_summary(user, filters: ResolvedFilters) -> dict[str, Any]:
    current_docs = _visible_documents(user, filters, date_from=filters.date_from, date_to=filters.date_to)

    # تحديد نافذة المقارنة بشكل شفاف دون افتراض تواريخ وهمية لبيانات الفلتر الأساسي
    if filters.date_from and filters.date_to:
        span_days = max(1, (filters.date_to - filters.date_from).days + 1)
        prev_to = filters.date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=span_days - 1)
        comparison_note = (
            f"مقارنة الفترة المحددة ({filters.date_from:%Y-%m-%d} إلى {filters.date_to:%Y-%m-%d}) "
            f"مع الفترة السابقة المماثلة ({prev_from:%Y-%m-%d} إلى {prev_to:%Y-%m-%d} — {span_days} يوماً)."
        )
        prev_docs = _visible_documents(user, filters, date_from=prev_from, date_to=prev_to)
    elif filters.date_from and not filters.date_to:
        today = timezone.localdate()
        span_days = max(1, (today - filters.date_from).days + 1)
        prev_to = filters.date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=span_days - 1)
        comparison_note = (
            f"مقارنة الفترة منذ {filters.date_from:%Y-%m-%d} حتى اليوم "
            f"مع الفترة السابقة المماثلة ({prev_from:%Y-%m-%d} إلى {prev_to:%Y-%m-%d})."
        )
        prev_docs = _visible_documents(user, filters, date_from=prev_from, date_to=prev_to)
    elif filters.date_to and not filters.date_from:
        prev_to = filters.date_to - timedelta(days=30)
        prev_from = prev_to - timedelta(days=29)
        comparison_note = (
            f"لعدم تحديد تاريخ بداية، تم عرض الإجمالي التراكمي حتى {filters.date_to:%Y-%m-%d} "
            f"ومقارنته بنافذة الـ 30 يوماً السابقة ({prev_from:%Y-%m-%d} إلى {prev_to:%Y-%m-%d})."
        )
        prev_docs = _visible_documents(user, filters, date_from=prev_from, date_to=prev_to)
    else:
        today = timezone.localdate()
        cur_from = today - timedelta(days=29)
        prev_to = cur_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=29)
        comparison_note = (
            f"دون تحديد تواريخ، يعرض التقرير الإجمالي الكلي للمستندات المرئية؛ "
            f"وللمقارنة الزمنية قورنت آخر 30 يوماً ({cur_from:%Y-%m-%d} – {today:%Y-%m-%d}) "
            f"مع الـ 30 يوماً السابقة ({prev_from:%Y-%m-%d} – {prev_to:%Y-%m-%d})."
        )
        prev_docs = _visible_documents(user, filters, date_from=prev_from, date_to=prev_to)

    def _counts(docs_list):
        inc = sum(1 for d, *_ in docs_list if d.source_type == Document.SourceType.INCOMING)
        out = sum(1 for d, *_ in docs_list if d.source_type == Document.SourceType.OUTGOING)
        intr = sum(1 for d, *_ in docs_list if d.source_type == Document.SourceType.INTERNAL)
        return {"INCOMING": inc, "OUTGOING": out, "INTERNAL": intr, "TOTAL": len(docs_list)}

    cur_c = _counts(current_docs)
    if not filters.date_from and not filters.date_to:
        today = timezone.localdate()
        cur_30_docs = _visible_documents(user, filters, date_from=today - timedelta(days=29), date_to=today)
        cmp_c = _counts(cur_30_docs)
    else:
        cmp_c = cur_c
    prev_c = _counts(prev_docs)

    rows = []
    for key, label in [
        ("INCOMING", "مستندات واردة"),
        ("OUTGOING", "مستندات صادرة"),
        ("INTERNAL", "مستندات داخلية"),
        ("TOTAL", "الإجمالي الكلي للمستندات"),
    ]:
        diff = cmp_c[key] - prev_c[key]
        rows.append(
            {
                "source_label": label,
                "current_total": cur_c[key],
                "period_compare_total": cmp_c[key],
                "previous_total": prev_c[key],
                "diff": diff,
                "pct_change": _pct_change(cmp_c[key], prev_c[key]),
            }
        )

    return {
        "kpis": [
            {"label": "إجمالي المستندات المرئية", "value": cur_c["TOTAL"], "tone": "blue"},
            {"label": "المستندات الواردة", "value": cur_c["INCOMING"], "tone": "green"},
            {"label": "المستندات الصادرة", "value": cur_c["OUTGOING"], "tone": "amber"},
            {"label": "المستندات الداخلية", "value": cur_c["INTERNAL"], "tone": "neutral"},
        ],
        "method_note": comparison_note,
        "columns": [
            {"key": "source_label", "label": "تصنيف المستند", "type": "text"},
            {"key": "current_total", "label": "العدد في النطاق المحدد", "type": "number"},
            {"key": "period_compare_total", "label": "عدد فترة المقارنة الحالية", "type": "number"},
            {"key": "previous_total", "label": "الفترة السابقة المماثلة", "type": "number"},
            {"key": "diff", "label": "الفارق العددي", "type": "number"},
            {"key": "pct_change", "label": "نسبة التغير", "type": "text"},
        ],
        "rows": rows,
    }


def _build_documents_by_org(user, filters: ResolvedFilters) -> dict[str, Any]:
    docs = _visible_documents(user, filters, date_from=filters.date_from, date_to=filters.date_to)
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for doc, _subj, doc_sector, doc_unit in docs:
        sec_name = doc_sector.name if doc_sector else "غير محدد"
        gd_name, section_name = _resolve_general_directorate_and_section(doc_unit)
        key = (sec_name, gd_name, section_name)
        if key not in grouped:
            grouped[key] = {
                "sector_name": sec_name,
                "gd_name": gd_name,
                "section_name": section_name,
                "total": 0,
                "incoming": 0,
                "outgoing": 0,
                "internal": 0,
                "confidential": 0,
            }
        bucket = grouped[key]
        bucket["total"] += 1
        if doc.source_type == Document.SourceType.INCOMING:
            bucket["incoming"] += 1
        elif doc.source_type == Document.SourceType.OUTGOING:
            bucket["outgoing"] += 1
        else:
            bucket["internal"] += 1
        if doc.confidentiality.rank >= 2:
            bucket["confidential"] += 1

    rows = sorted(grouped.values(), key=lambda r: (-r["total"], r["sector_name"], r["section_name"]))
    return {
        "kpis": [
            {"label": "إجمالي المستندات الموزعة", "value": len(docs), "tone": "blue"},
            {"label": "عدد الوحدات / الأقسام النشطة", "value": len(rows), "tone": "green"},
            {"label": "المستندات السرية / سري للغاية", "value": sum(r["confidential"] for r in rows), "tone": "red"},
        ],
        "method_note": "يتم ربط كل مستند بقطاع ووحدة الموضوع الرئيسي المرتبط به، أو بوحدة منشئ السجل للمستندات المستقلة، مع فرض العزل التنظيمي الكامل.",
        "columns": [
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "gd_name", "label": "الإدارة العامة / الأعلى", "type": "text"},
            {"key": "section_name", "label": "القسم / الوحدة", "type": "text"},
            {"key": "total", "label": "الإجمالي", "type": "number"},
            {"key": "incoming", "label": "الوارد", "type": "number"},
            {"key": "outgoing", "label": "الصادر", "type": "number"},
            {"key": "internal", "label": "الداخلي", "type": "number"},
            {"key": "confidential", "label": "مستندات سرية", "type": "number"},
        ],
        "rows": rows,
    }


def _build_subjects_status(user, filters: ResolvedFilters) -> dict[str, Any]:
    subjects = list(_scoped_subjects_qs(user, filters))
    closed_statuses = {Subject.Status.CLOSED, Subject.Status.COMPLETED}
    total = len(subjects)
    closed_cnt = sum(1 for s in subjects if s.status in closed_statuses)
    suspended_cnt = sum(1 for s in subjects if s.status == Subject.Status.SUSPENDED)
    open_cnt = total - closed_cnt
    closure_rate = round((closed_cnt / total) * 100, 1) if total else 0.0

    rows = []
    for s in subjects:
        is_closed = s.status in closed_statuses
        rows.append(
            {
                "internal_number": s.internal_number,
                "title": s.title,
                "sector_name": s.sector.name,
                "org_unit_name": s.org_unit.name,
                "tx_name": s.transaction_type.name,
                "category_state": "مغلق / منتهٍ" if is_closed else "مفتوح / جارٍ",
                "status_display": s.get_status_display(),
                "created_at": s.created_at.strftime("%Y-%m-%d %H:%M"),
                "closed_at": s.closed_at.strftime("%Y-%m-%d %H:%M") if s.closed_at else "—",
                "url_name": "subjects:subject_detail",
                "url_arg": s.id,
            }
        )

    return {
        "kpis": [
            {"label": "إجمالي الموضوعات", "value": total, "tone": "blue"},
            {"label": "الموضوعات المفتوحة", "value": open_cnt, "tone": "amber"},
            {"label": "الموضوعات المعلقة", "value": suspended_cnt, "tone": "red"},
            {"label": "الموضوعات المغلقة (%)", "value": f"{closed_cnt} ({closure_rate}%)", "tone": "green"},
        ],
        "method_note": "تشمل «الموضوعات المفتوحة» جميع الموضوعات الجارية أو المعلقة أو قيد الاعتماد، بينما تمثل «الموضوعات المغلقة» الحالتين CLOSED وCOMPLETED.",
        "columns": [
            {"key": "internal_number", "label": "الرقم الداخلي", "type": "link"},
            {"key": "title", "label": "عنوان الموضوع", "type": "text"},
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "org_unit_name", "label": "الوحدة التنظيمية", "type": "text"},
            {"key": "tx_name", "label": "نوع المعاملة", "type": "text"},
            {"key": "category_state", "label": "التصنيف (مفتوح/مغلق)", "type": "text"},
            {"key": "status_display", "label": "الحالة التفصيلية", "type": "text"},
            {"key": "created_at", "label": "تاريخ الإنشاء", "type": "date"},
            {"key": "closed_at", "label": "تاريخ الإغلاق", "type": "date"},
        ],
        "rows": rows,
    }


def _build_suspended_subjects(user, filters: ResolvedFilters) -> dict[str, Any]:
    visible_subjects = _scoped_subjects_qs(user, filters, apply_created_dates=False)
    visible_ids = list(visible_subjects.values_list("id", flat=True))
    qs = SubjectSuspension.objects.filter(subject_id__in=visible_ids).select_related(
        "subject", "subject__sector", "subject__org_unit", "reason_ref", "suspended_by"
    )
    if filters.date_from:
        qs = qs.filter(suspended_at__gte=_to_aware_start(filters.date_from))
    if filters.date_to:
        qs = qs.filter(suspended_at__lte=_to_aware_end(filters.date_to))

    suspensions = list(qs.order_by("-suspended_at"))
    active_count = sum(1 for sp in suspensions if not sp.is_fulfilled)
    fulfilled_count = sum(1 for sp in suspensions if sp.is_fulfilled)

    rows = []
    for sp in suspensions:
        rows.append(
            {
                "internal_number": sp.subject.internal_number,
                "title": sp.subject.title,
                "sector_name": sp.subject.sector.name,
                "reason_name": sp.reason_ref.name if sp.reason_ref else "سبب مخصص",
                "reason_details": sp.reason_details,
                "required_from": sp.required_from,
                "required_item": sp.required_item,
                "suspended_at": sp.suspended_at.strftime("%Y-%m-%d %H:%M"),
                "expected_follow_up": sp.expected_follow_up_date.strftime("%Y-%m-%d") if sp.expected_follow_up_date else "—",
                "fulfillment_state": "تم الاستيفاء" if sp.is_fulfilled else "معلق حالياً",
                "url_name": "subjects:subject_detail",
                "url_arg": sp.subject_id,
            }
        )

    return {
        "kpis": [
            {"label": "إجمالي سجلات التعليق", "value": len(suspensions), "tone": "blue"},
            {"label": "معلق حالياً (بانتظار استيفاء)", "value": active_count, "tone": "red"},
            {"label": "تم استيفاؤه واستئنافه", "value": fulfilled_count, "tone": "green"},
        ],
        "method_note": "مصدر البيانات المباشر هو نموذج SubjectSuspension مع إظهار أسباب التعليق المرجعية (SuspensionReason) وما تم استيفاؤه.",
        "columns": [
            {"key": "internal_number", "label": "رقم الموضوع", "type": "link"},
            {"key": "title", "label": "عنوان الموضوع", "type": "text"},
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "reason_name", "label": "سبب التعليق المرجعي", "type": "text"},
            {"key": "reason_details", "label": "تفاصيل السبب", "type": "text"},
            {"key": "required_from", "label": "المطلوب منه", "type": "text"},
            {"key": "required_item", "label": "المستند / الإجراء المطلوب", "type": "text"},
            {"key": "suspended_at", "label": "تاريخ التعليق", "type": "date"},
            {"key": "expected_follow_up", "label": "متابعة متوقعة", "type": "date"},
            {"key": "fulfillment_state", "label": "حالة الاستيفاء", "type": "text"},
        ],
        "rows": rows,
    }


def _build_overdue_tasks(user, filters: ResolvedFilters) -> dict[str, Any]:
    today = timezone.localdate()
    visible_subjects = _scoped_subjects_qs(user, filters, apply_created_dates=False)
    visible_ids = list(visible_subjects.values_list("id", flat=True))

    qs = (
        Task.objects.filter(subject_id__in=visible_ids, due_date__lt=today)
        .exclude(status__in=[Task.TaskStatus.COMPLETED, Task.TaskStatus.CANCELLED])
        .select_related("subject", "subject__sector", "assigned_to", "assigned_unit", "priority")
    )
    if filters.date_from:
        qs = qs.filter(due_date__gte=filters.date_from)
    if filters.date_to:
        qs = qs.filter(due_date__lte=filters.date_to)

    tasks = list(qs.order_by("due_date", "-assigned_at"))
    max_overdue = max([(today - t.due_date).days for t in tasks], default=0)

    rows = []
    for t in tasks:
        overdue_days = (today - t.due_date).days
        rows.append(
            {
                "task_title": t.title,
                "subject_number": t.subject.internal_number,
                "subject_title": t.subject.title,
                "sector_name": t.subject.sector.name,
                "assigned_to": str(t.assigned_to),
                "assigned_unit": t.assigned_unit.name if t.assigned_unit else t.subject.org_unit.name,
                "priority_name": t.priority.name,
                "due_date": t.due_date.strftime("%Y-%m-%d"),
                "overdue_days": overdue_days,
                "status_display": t.get_status_display(),
                "url_name": "subjects:subject_detail",
                "url_arg": t.subject_id,
            }
        )

    return {
        "kpis": [
            {"label": "إجمالي المهام المتأخرة", "value": len(tasks), "tone": "red"},
            {"label": "أقصى تأخير (أيام)", "value": max_overdue, "tone": "amber"},
            {"label": "عدد الموظفين المعنيين", "value": len({t.assigned_to_id for t in tasks}), "tone": "blue"},
        ],
        "method_note": "تشمل كل مهمة تجاوزت تاريخ الاستحقاق (due_date < اليوم) ولم تصل إلى حالة «مكتملة» (COMPLETED) أو «ملغاة» (CANCELLED).",
        "columns": [
            {"key": "task_title", "label": "المهمة", "type": "text"},
            {"key": "subject_number", "label": "رقم الموضوع", "type": "link"},
            {"key": "subject_title", "label": "عنوان الموضوع", "type": "text"},
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "assigned_to", "label": "الموظف المكلف", "type": "text"},
            {"key": "assigned_unit", "label": "الوحدة", "type": "text"},
            {"key": "priority_name", "label": "الأولوية", "type": "text"},
            {"key": "due_date", "label": "تاريخ الاستحقاق", "type": "date"},
            {"key": "overdue_days", "label": "أيام التأخير", "type": "number"},
            {"key": "status_display", "label": "حالة المهمة", "type": "text"},
        ],
        "rows": rows,
    }


def _resolve_reliable_creation_event(subject: Subject, logs: list[ActivityLog], history: list[SubjectStatusHistory]):
    for log in logs:
        if log.action_type == "SUBJECT_CREATED":
            return log.created_at, "ActivityLog(SUBJECT_CREATED)"
    if history:
        earliest = min(history, key=lambda h: (h.changed_at, h.id))
        return earliest.changed_at, "SubjectStatusHistory(first)"
    if subject.created_at:
        return subject.created_at, "Subject.created_at"
    return None, "missing"


def _resolve_reliable_closure_event(subject: Subject, logs: list[ActivityLog], history: list[SubjectStatusHistory]):
    closure_logs = [lg for lg in logs if lg.action_type == "SUBJECT_CLOSED"]
    closure_hist = [h for h in history if h.to_status == Subject.Status.CLOSED]
    duplicate_closures = max(len(closure_logs), len(closure_hist)) > 1

    if closure_logs:
        latest = max(closure_logs, key=lambda lg: (lg.created_at, lg.id))
        return latest.created_at, "ActivityLog(SUBJECT_CLOSED)", duplicate_closures
    if closure_hist:
        latest_h = max(closure_hist, key=lambda h: (h.changed_at, h.id))
        return latest_h.changed_at, "SubjectStatusHistory(CLOSED)", duplicate_closures
    if subject.closed_at:
        return subject.closed_at, "Subject.closed_at", duplicate_closures
    return None, "missing", False


def _build_avg_completion_time(user, filters: ResolvedFilters) -> dict[str, Any]:
    # استبعاد الموضوعات غير المغلقة تماماً كما ينص ضابط التقرير
    closed_qs = _scoped_subjects_qs(user, filters, apply_created_dates=False).filter(
        status=Subject.Status.CLOSED
    ).prefetch_related("activity_logs", "status_history")

    all_closed = list(closed_qs)
    durations_hours: list[float] = []
    durations_days: list[float] = []
    excluded_missing_count = 0
    duplicate_events_count = 0
    rows = []

    for s in all_closed:
        logs = list(s.activity_logs.all())
        history = list(s.status_history.all())
        start_ts, start_src = _resolve_reliable_creation_event(s, logs, history)
        end_ts, end_src, has_dup = _resolve_reliable_closure_event(s, logs, history)

        if start_ts is None or end_ts is None or end_ts < start_ts:
            excluded_missing_count += 1
            continue

        if filters.date_from and end_ts < _to_aware_start(filters.date_from):
            continue
        if filters.date_to and end_ts > _to_aware_end(filters.date_to):
            continue

        if has_dup:
            duplicate_events_count += 1

        delta_sec = (end_ts - start_ts).total_seconds()
        hours = round(delta_sec / 3600.0, 2)
        days = round(delta_sec / 86400.0, 2)
        durations_hours.append(hours)
        durations_days.append(days)

        rows.append(
            {
                "internal_number": s.internal_number,
                "title": s.title,
                "sector_name": s.sector.name,
                "tx_name": s.transaction_type.name,
                "start_ts": start_ts.strftime("%Y-%m-%d %H:%M"),
                "end_ts": end_ts.strftime("%Y-%m-%d %H:%M"),
                "duration_days": days,
                "duration_hours": hours,
                "event_sources": f"{start_src} ← {end_src}" + (" (تعدد إغلاق/إعادة فتح)" if has_dup else ""),
                "url_name": "subjects:subject_detail",
                "url_arg": s.id,
            }
        )

    evaluated_count = len(rows)
    avg_days = round(sum(durations_days) / evaluated_count, 2) if evaluated_count else 0.0
    avg_hours = round(sum(durations_hours) / evaluated_count, 2) if evaluated_count else 0.0
    min_days = min(durations_days) if durations_days else 0.0
    max_days = max(durations_days) if durations_days else 0.0

    rows.sort(key=lambda r: (-r["duration_days"], r["internal_number"]))

    method_note = (
        "تُحتسب المدة للموضوعات المغلقة فقط من حدث الإنشاء الموثوق (ActivityLog: SUBJECT_CREATED ← SubjectStatusHistory ← created_at) "
        "إلى أحدث حدث إغلاق موثوق (ActivityLog: SUBJECT_CLOSED ← SubjectStatusHistory[CLOSED] ← closed_at). "
        f"تم استبعاد ({excluded_missing_count}) موضوعات لغياب أو تناقض أحداث الإنشاء/الإغلاق، "
        f"ورُصدت ({duplicate_events_count}) حالات تعدد إغلاق (نتيجة إعادة فتح سابقة) باعتماد الإغلاق النهائي الأحدث."
    )

    return {
        "kpis": [
            {"label": "الموضوعات المغلقة المحتسبة", "value": evaluated_count, "tone": "blue"},
            {"label": "متوسط زمن الإنجاز (أيام)", "value": avg_days, "tone": "green"},
            {"label": "متوسط زمن الإنجاز (ساعات)", "value": avg_hours, "tone": "amber"},
            {"label": "أطول / أقصر مدة (أيام)", "value": f"{max_days} / {min_days}", "tone": "neutral"},
        ],
        "method_note": method_note,
        "meta": {
            "evaluated_count": evaluated_count,
            "excluded_missing_count": excluded_missing_count,
            "duplicate_events_count": duplicate_events_count,
            "avg_days": avg_days,
            "avg_hours": avg_hours,
        },
        "columns": [
            {"key": "internal_number", "label": "رقم الموضوع", "type": "link"},
            {"key": "title", "label": "عنوان الموضوع", "type": "text"},
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "tx_name", "label": "نوع المعاملة", "type": "text"},
            {"key": "start_ts", "label": "تاريخ حدث الإنشاء", "type": "date"},
            {"key": "end_ts", "label": "تاريخ حدث الإغلاق", "type": "date"},
            {"key": "duration_days", "label": "المدة (أيام)", "type": "number"},
            {"key": "duration_hours", "label": "المدة (ساعات)", "type": "number"},
            {"key": "event_sources", "label": "مصدر الأحداث والملاحظات", "type": "text"},
        ],
        "rows": rows,
    }


def _build_referrals_by_unit(user, filters: ResolvedFilters) -> dict[str, Any]:
    visible_subjects = _scoped_subjects_qs(user, filters, apply_created_dates=False)
    visible_ids = list(visible_subjects.values_list("id", flat=True))

    qs = ReferralRecipient.objects.filter(referral__subject_id__in=visible_ids).select_related(
        "referral",
        "referral__subject__sector",
        "referral__subject__org_unit",
        "target_unit",
        "target_unit__sector",
        "target_user__employee__current_unit",
        "target_user__employee__current_unit__sector",
    )
    if filters.date_from:
        qs = qs.filter(referral__created_at__gte=_to_aware_start(filters.date_from))
    if filters.date_to:
        qs = qs.filter(referral__created_at__lte=_to_aware_end(filters.date_to))

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in qs:
        unit = rec.target_unit or (rec.target_user.current_unit if rec.target_user else None) or rec.referral.subject.org_unit
        sector = unit.sector if unit else rec.referral.subject.sector
        if not filters.is_org_wide and sector and sector.id not in filters.allowed_sector_ids:
            continue
        if filters.sector and (not sector or sector.id != filters.sector.id):
            continue
        sec_name = sector.name if sector else "غير محدد"
        unit_name = unit.name if unit else "غير محدد"
        key = (sec_name, unit_name)
        if key not in grouped:
            grouped[key] = {
                "sector_name": sec_name,
                "unit_name": unit_name,
                "total": 0,
                "pending": 0,
                "received": 0,
                "responded": 0,
                "for_info": 0,
            }
        b = grouped[key]
        b["total"] += 1
        if rec.status in {ReferralRecipient.RecipientStatus.PENDING, ReferralRecipient.RecipientStatus.WAITING_TURN}:
            b["pending"] += 1
        elif rec.status == ReferralRecipient.RecipientStatus.RECEIVED:
            b["received"] += 1
        elif rec.status == ReferralRecipient.RecipientStatus.RESPONDED:
            b["responded"] += 1
        if rec.referral.purpose == Referral.Purpose.FOR_INFO:
            b["for_info"] += 1

    rows = sorted(grouped.values(), key=lambda r: (-r["total"], r["sector_name"], r["unit_name"]))
    return {
        "kpis": [
            {"label": "إجمالي بنود الإحالات", "value": sum(r["total"] for r in rows), "tone": "blue"},
            {"label": "الوحدات المستلمة", "value": len(rows), "tone": "green"},
            {"label": "بانتظار الاستلام / الدور", "value": sum(r["pending"] for r in rows), "tone": "amber"},
            {"label": "تم الرد / التنفيذ", "value": sum(r["responded"] for r in rows), "tone": "neutral"},
        ],
        "method_note": "يُحتسب عدد الإحالات على مستوى كل وحدة تنظيمية مستهدفة مع مراعاة عزل القطاعات وصلاحيات الرؤية.",
        "columns": [
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "unit_name", "label": "الإدارة / القسم المحال إليه", "type": "text"},
            {"key": "total", "label": "إجمالي الإحالات", "type": "number"},
            {"key": "pending", "label": "بانتظار الاستلام", "type": "number"},
            {"key": "received", "label": "تم الاستلام", "type": "number"},
            {"key": "responded", "label": "تم الرد / التنفيذ", "type": "number"},
            {"key": "for_info", "label": "إحالات للاطلاع", "type": "number"},
        ],
        "rows": rows,
    }


def _build_employee_workload(user, filters: ResolvedFilters) -> dict[str, Any]:
    today = timezone.localdate()
    visible_subjects = _scoped_subjects_qs(user, filters, apply_created_dates=False)
    visible_ids = list(visible_subjects.values_list("id", flat=True))

    qs = Task.objects.filter(subject_id__in=visible_ids).select_related(
        "assigned_to",
        "assigned_to__employee__current_unit",
        "assigned_to__employee__current_unit__sector",
        "assigned_unit",
        "subject__sector",
    )
    if filters.date_from:
        qs = qs.filter(assigned_at__gte=_to_aware_start(filters.date_from))
    if filters.date_to:
        qs = qs.filter(assigned_at__lte=_to_aware_end(filters.date_to))

    grouped: dict[int, dict[str, Any]] = {}
    for t in qs:
        emp_user = t.assigned_to
        unit = emp_user.current_unit or t.assigned_unit
        sector = (unit.sector if unit else t.subject.sector)
        if not filters.is_org_wide and sector and sector.id not in filters.allowed_sector_ids:
            continue
        if emp_user.id not in grouped:
            grouped[emp_user.id] = {
                "employee_name": str(emp_user),
                "unit_name": unit.name if unit else "—",
                "sector_name": sector.name if sector else "—",
                "total_tasks": 0,
                "open_tasks": 0,
                "completed_tasks": 0,
                "overdue_tasks": 0,
                "completion_rate": "0%",
            }
        b = grouped[emp_user.id]
        b["total_tasks"] += 1
        if t.status == Task.TaskStatus.COMPLETED:
            b["completed_tasks"] += 1
        elif t.status not in {Task.TaskStatus.CANCELLED, Task.TaskStatus.REJECTED}:
            b["open_tasks"] += 1
            if t.due_date and t.due_date < today:
                b["overdue_tasks"] += 1

    rows = []
    for b in grouped.values():
        rate = round((b["completed_tasks"] / b["total_tasks"]) * 100, 1) if b["total_tasks"] else 0.0
        b["completion_rate"] = f"{rate}%"
        rows.append(b)

    rows.sort(key=lambda r: (-r["total_tasks"], -r["overdue_tasks"], r["employee_name"]))
    return {
        "kpis": [
            {"label": "عدد الموظفين المكلفين", "value": len(rows), "tone": "blue"},
            {"label": "إجمالي المهام", "value": sum(r["total_tasks"] for r in rows), "tone": "neutral"},
            {"label": "المهام المكتملة", "value": sum(r["completed_tasks"] for r in rows), "tone": "green"},
            {"label": "المهام المتأخرة", "value": sum(r["overdue_tasks"] for r in rows), "tone": "red"},
        ],
        "method_note": "يعرض المهام المسندة لكل موظف ضمن نطاق القطاع والصلاحيات، مصنفة إلى مكتملة وجارية ومتأخرة.",
        "columns": [
            {"key": "employee_name", "label": "الموظف", "type": "text"},
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "unit_name", "label": "الوحدة التنظيمية", "type": "text"},
            {"key": "total_tasks", "label": "إجمالي المهام", "type": "number"},
            {"key": "completed_tasks", "label": "المكتملة", "type": "number"},
            {"key": "open_tasks", "label": "الجارية / المفتوحة", "type": "number"},
            {"key": "overdue_tasks", "label": "المتأخرة", "type": "number"},
            {"key": "completion_rate", "label": "نسبة الإنجاز", "type": "text"},
        ],
        "rows": rows,
    }


def _build_issued_decisions(user, filters: ResolvedFilters) -> dict[str, Any]:
    visible_subjects = _scoped_subjects_qs(user, filters, apply_created_dates=False)
    visible_ids = list(visible_subjects.values_list("id", flat=True))

    issued_statuses = [
        Decision.Status.APPROVED,
        Decision.Status.ISSUED,
        Decision.Status.DISTRIBUTING,
        Decision.Status.EXECUTING,
        Decision.Status.COMPLETED,
    ]
    qs = Decision.objects.filter(
        subject_id__in=visible_ids,
        status__in=issued_statuses,
    ).select_related("subject", "subject__sector", "created_by", "approved_by")
    if filters.date_from:
        qs = qs.filter(Q(issued_date__gte=filters.date_from) | Q(issued_date__isnull=True, created_at__gte=_to_aware_start(filters.date_from)))
    if filters.date_to:
        qs = qs.filter(Q(issued_date__lte=filters.date_to) | Q(issued_date__isnull=True, created_at__lte=_to_aware_end(filters.date_to)))

    decisions = list(qs.order_by("-issued_date", "-created_at"))
    rows = []
    for d in decisions:
        rows.append(
            {
                "decision_number": d.decision_number,
                "title": d.title,
                "decision_type": d.get_decision_type_display(),
                "subject_number": d.subject.internal_number,
                "sector_name": d.subject.sector.name,
                "issuing_authority": d.issuing_authority,
                "approving_authority": d.approving_authority,
                "issued_date": d.issued_date.strftime("%Y-%m-%d") if d.issued_date else d.created_at.strftime("%Y-%m-%d"),
                "status_display": d.get_status_display(),
                "url_name": "decisions:decision_detail",
                "url_arg": d.id,
            }
        )

    return {
        "kpis": [
            {"label": "إجمالي القرارات الصادرة", "value": len(decisions), "tone": "blue"},
            {"label": "المكتمل تنفيذها", "value": sum(1 for d in decisions if d.status == Decision.Status.COMPLETED), "tone": "green"},
            {"label": "قيد التوزيع / التنفيذ", "value": sum(1 for d in decisions if d.status in {Decision.Status.ISSUED, Decision.Status.DISTRIBUTING, Decision.Status.EXECUTING}), "tone": "amber"},
        ],
        "method_note": "تشمل القرارات التي اعتمدت أو صدرت رسمياً ضمن الموضوعات المصرح لك برؤيتها.",
        "columns": [
            {"key": "decision_number", "label": "رقم القرار", "type": "link"},
            {"key": "title", "label": "عنوان القرار", "type": "text"},
            {"key": "decision_type", "label": "النوع", "type": "text"},
            {"key": "subject_number", "label": "الموضوع المرجعي", "type": "text"},
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "issuing_authority", "label": "جهة الإصدار", "type": "text"},
            {"key": "approving_authority", "label": "جهة الاعتماد", "type": "text"},
            {"key": "issued_date", "label": "تاريخ الإصدار", "type": "date"},
            {"key": "status_display", "label": "الحالة", "type": "text"},
        ],
        "rows": rows,
    }


def _build_incomplete_decisions(user, filters: ResolvedFilters) -> dict[str, Any]:
    today = timezone.localdate()
    visible_subjects = _scoped_subjects_qs(user, filters, apply_created_dates=False)
    visible_ids = list(visible_subjects.values_list("id", flat=True))

    qs = (
        DecisionExecutionItem.objects.filter(decision__subject_id__in=visible_ids)
        .exclude(decision__status=Decision.Status.CANCELLED)
        .exclude(execution_status=DecisionExecutionItem.ExecutionStatus.COMPLETED)
        .select_related("decision", "decision__subject", "decision__subject__sector", "assigned_unit", "assigned_user")
    )
    if filters.date_from:
        qs = qs.filter(assigned_at__gte=_to_aware_start(filters.date_from))
    if filters.date_to:
        qs = qs.filter(assigned_at__lte=_to_aware_end(filters.date_to))

    items = list(qs.order_by("due_date", "id"))
    overdue_cnt = sum(1 for it in items if it.due_date and it.due_date < today)

    rows = []
    for it in items:
        is_item_overdue = bool(it.due_date and it.due_date < today)
        rows.append(
            {
                "decision_number": it.decision.decision_number,
                "decision_title": it.decision.title,
                "subject_number": it.decision.subject.internal_number,
                "sector_name": it.decision.subject.sector.name,
                "assigned_unit": it.assigned_unit.name,
                "assigned_user": str(it.assigned_user),
                "required_action": it.required_action,
                "due_date": it.due_date.strftime("%Y-%m-%d") if it.due_date else "—",
                "execution_status": it.get_execution_status_display() + (" (متأخر)" if is_item_overdue else ""),
                "url_name": "decisions:decision_detail",
                "url_arg": it.decision_id,
            }
        )

    return {
        "kpis": [
            {"label": "بنود التنفيذ غير المكتملة", "value": len(items), "tone": "amber"},
            {"label": "القرارات المتأثر تنفيذها", "value": len({it.decision_id for it in items}), "tone": "blue"},
            {"label": "بنود متجاوزة للموعد", "value": overdue_cnt, "tone": "red"},
        ],
        "method_note": "يعتمد التقرير مباشرة على سجل DecisionExecutionItem برصد كافة البنود التي لم تصل إلى حالة «تم التنفيذ» (COMPLETED).",
        "columns": [
            {"key": "decision_number", "label": "رقم القرار", "type": "link"},
            {"key": "decision_title", "label": "عنوان القرار", "type": "text"},
            {"key": "subject_number", "label": "رقم الموضوع", "type": "text"},
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "assigned_unit", "label": "الجهة المكلفة بالتنفيذ", "type": "text"},
            {"key": "assigned_user", "label": "المسؤول", "type": "text"},
            {"key": "required_action", "label": "المطلوب تنفيذه", "type": "text"},
            {"key": "due_date", "label": "الموعد النهائي", "type": "date"},
            {"key": "execution_status", "label": "حالة التنفيذ", "type": "text"},
        ],
        "rows": rows,
    }


def _build_committee_subjects(user, filters: ResolvedFilters) -> dict[str, Any]:
    visible_subjects = _scoped_subjects_qs(user, filters, apply_created_dates=False)
    visible_ids = list(visible_subjects.values_list("id", flat=True))

    qs = CommitteeAgendaItem.objects.filter(subject_id__in=visible_ids).select_related(
        "meeting", "meeting__committee", "subject", "subject__sector", "subject__transaction_type", "memo"
    )
    if filters.date_from:
        qs = qs.filter(meeting__meeting_date__gte=filters.date_from)
    if filters.date_to:
        qs = qs.filter(meeting__meeting_date__lte=filters.date_to)

    items = list(qs.order_by("-meeting__meeting_date", "id"))
    rows = []
    for it in items:
        rows.append(
            {
                "committee_name": it.meeting.committee.name,
                "meeting_number": it.meeting.meeting_number,
                "meeting_date": it.meeting.meeting_date.strftime("%Y-%m-%d"),
                "subject_number": it.subject.internal_number,
                "subject_title": it.subject.title,
                "sector_name": it.subject.sector.name,
                "resolution_type": it.get_resolution_type_display(),
                "recommendation": it.recommendation or "—",
                "resolution_text": it.resolution_text or "—",
                "url_name": "subjects:subject_detail",
                "url_arg": it.subject_id,
            }
        )

    approved_cnt = sum(1 for it in items if it.resolution_type == CommitteeAgendaItem.ResolutionType.APPROVED)
    pending_cnt = sum(1 for it in items if it.resolution_type == CommitteeAgendaItem.ResolutionType.PENDING)
    return {
        "kpis": [
            {"label": "إجمالي البنود المعروضة", "value": len(items), "tone": "blue"},
            {"label": "بنود تمت الموافقة عليها", "value": approved_cnt, "tone": "green"},
            {"label": "بنود قيد البحث", "value": pending_cnt, "tone": "amber"},
        ],
        "method_note": "يعرض جميع الموضوعات المدرجة في جداول أعمال اللجان (CommitteeAgendaItem) وتوصياتها ضمن نطاق صلاحيات المستخدم.",
        "columns": [
            {"key": "committee_name", "label": "اللجنة", "type": "text"},
            {"key": "meeting_number", "label": "رقم الجلسة", "type": "text"},
            {"key": "meeting_date", "label": "تاريخ الاجتماع", "type": "date"},
            {"key": "subject_number", "label": "رقم الموضوع", "type": "link"},
            {"key": "subject_title", "label": "عنوان الموضوع", "type": "text"},
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "resolution_type", "label": "نتيجة العرض", "type": "text"},
            {"key": "recommendation", "label": "التوصية", "type": "text"},
            {"key": "resolution_text", "label": "قرار اللجنة", "type": "text"},
        ],
        "rows": rows,
    }


def _build_confidential_audit(user, filters: ResolvedFilters) -> dict[str, Any]:
    if not can_view_confidential_audit_report(user):
        raise PermissionDenied("الاطلاع على تقرير حركة المستندات السرية مقصور على المصرح لهم بالتدقيق الأمني أو السرية.")

    audit_actions = [
        "DOCUMENT_PREVIEW",
        "ATTACHMENT_DOWNLOAD",
        "DOCUMENT_VIEW",
        "UNAUTHORIZED_ATTACHMENT_ACCESS",
        "ATTACHMENT_INTEGRITY_FAILED",
    ]
    qs = AuditLog.objects.filter(action__in=audit_actions).select_related("actor_user")
    if filters.date_from:
        qs = qs.filter(created_at__gte=_to_aware_start(filters.date_from))
    if filters.date_to:
        qs = qs.filter(created_at__lte=_to_aware_end(filters.date_to))

    logs = list(qs.order_by("-created_at")[:500])

    att_ids = []
    doc_ids = []
    for lg in logs:
        if lg.model_name == "Attachment" and str(lg.object_id).isdigit():
            att_ids.append(int(lg.object_id))
        elif lg.model_name == "Document" and str(lg.object_id).isdigit():
            doc_ids.append(int(lg.object_id))

    attachments_map = {
        a.id: a
        for a in Attachment.objects.filter(id__in=att_ids).select_related(
            "document_version__document__confidentiality",
            "document_version__document__created_by__employee__current_unit__sector",
        ).prefetch_related("document_version__document__subjectdocumentlink_set__subject__sector")
    }
    docs_map = {
        d.id: d
        for d in Document.objects.filter(id__in=doc_ids).select_related(
            "confidentiality",
            "created_by__employee__current_unit__sector",
        ).prefetch_related("subjectdocumentlink_set__subject__sector")
    }

    rows = []
    for lg in logs:
        doc = None
        if lg.model_name == "Attachment" and str(lg.object_id).isdigit():
            att = attachments_map.get(int(lg.object_id))
            doc = att.document_version.document if att else None
        elif lg.model_name == "Document" and str(lg.object_id).isdigit():
            doc = docs_map.get(int(lg.object_id))

        conf_rank = doc.confidentiality.rank if doc else None
        conf_name = doc.confidentiality.name if doc else (lg.after_state.get("confidentiality") or "سري")
        if conf_rank is not None and conf_rank < 2 and lg.action != "UNAUTHORIZED_ATTACHMENT_ACCESS":
            continue

        # عزل القطاع للمديرين غير الشاملين
        doc_sector = None
        if doc is not None:
            links = list(doc.subjectdocumentlink_set.all())
            doc_sector = links[0].subject.sector if links else (doc.created_by.current_sector if doc.created_by else None)
            if not filters.is_org_wide:
                if doc_sector and doc_sector.id not in filters.allowed_sector_ids:
                    continue
                if not PermissionService.can_view_document(user, doc) and lg.actor_user_id != user.id:
                    continue
        if filters.sector and (not doc_sector or doc_sector.id != filters.sector.id):
            continue

        rows.append(
            {
                "created_at": lg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "action": lg.action,
                "actor": str(lg.actor_user) if lg.actor_user else "غير محدد",
                "doc_ref": doc.internal_number if doc else f"{lg.model_name} #{lg.object_id}",
                "doc_title": doc.title if doc else (lg.after_state.get("filename") or "—"),
                "confidentiality": conf_name,
                "sector_name": doc_sector.name if doc_sector else "عام",
                "outcome": lg.outcome,
                "ip_address": lg.ip_address or "—",
                "reason": lg.reason or "—",
            }
        )

    denied_cnt = sum(1 for r in rows if r["outcome"] == "DENIED")
    return {
        "kpis": [
            {"label": "إجمالي حركات المستندات السرية", "value": len(rows), "tone": "blue"},
            {"label": "عمليات ناجحة مسجلة", "value": len(rows) - denied_cnt, "tone": "green"},
            {"label": "محاولات مرفوضة / محظورة", "value": denied_cnt, "tone": "red"},
        ],
        "method_note": "تُستخرج السجلات من AuditLog مع التحقق من مستوى سرية المستند وعزل القطاعات وحجب التقرير تماماً عن غير المصرح لهم.",
        "columns": [
            {"key": "created_at", "label": "الوقت والتاريخ", "type": "date"},
            {"key": "action", "label": "الإجراء", "type": "text"},
            {"key": "actor", "label": "المستخدم", "type": "text"},
            {"key": "doc_ref", "label": "مرجع المستند", "type": "text"},
            {"key": "doc_title", "label": "عنوان المستند / الملف", "type": "text"},
            {"key": "confidentiality", "label": "درجة السرية", "type": "text"},
            {"key": "sector_name", "label": "القطاع", "type": "text"},
            {"key": "outcome", "label": "النتيجة", "type": "text"},
            {"key": "ip_address", "label": "عنوان IP", "type": "text"},
            {"key": "reason", "label": "التفاصيل", "type": "text"},
        ],
        "rows": rows,
    }


REPORT_BUILDERS = {
    "documents-summary": _build_documents_summary,
    "documents-by-org": _build_documents_by_org,
    "subjects-status": _build_subjects_status,
    "suspended-subjects": _build_suspended_subjects,
    "overdue-tasks": _build_overdue_tasks,
    "avg-completion-time": _build_avg_completion_time,
    "referrals-by-unit": _build_referrals_by_unit,
    "employee-workload": _build_employee_workload,
    "issued-decisions": _build_issued_decisions,
    "incomplete-decisions": _build_incomplete_decisions,
    "committee-subjects": _build_committee_subjects,
    "confidential-audit": _build_confidential_audit,
}


def build_report(slug: str, user, params) -> dict[str, Any]:
    definition = REPORT_MAP.get(slug)
    if definition is None:
        raise ValueError(f"تقرير غير معروف: {slug}")
    if definition.restricted_audit and not can_view_confidential_audit_report(user):
        raise PermissionDenied("ليس لديك صلاحية الاطلاع على تقرير المستندات السرية.")

    filters = resolve_report_filters(user, params)
    builder = REPORT_BUILDERS[slug]
    payload = builder(user, filters)
    payload["definition"] = definition
    payload["filters"] = filters
    payload["generated_at"] = timezone.localtime()
    return payload


def get_available_reports_for_user(user) -> list[ReportDefinition]:
    allow_audit = can_view_confidential_audit_report(user)
    return [r for r in REPORT_DEFINITIONS if (not r.restricted_audit or allow_audit)]
