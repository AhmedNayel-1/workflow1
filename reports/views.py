from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import render
from django.http import Http404

from accounts.services import PermissionService
from core.pdf_utils import build_institutional_pdf_bytes, pdf_http_response
from .exports import export_report_excel_response
from .services import REPORT_MAP, build_report, get_available_reports_for_user


@login_required
def reports_dashboard(request):
    """فهرس التقارير الإدارية والتشغيلية الاثني عشر مع روابط مستقلة لكل تقرير."""
    if not PermissionService.user_has_permission(request.user, "REPORTS_VIEW"):
        raise PermissionDenied("ليس لديك صلاحية عرض التقارير.")

    available_reports = get_available_reports_for_user(request.user)
    scope = PermissionService.describe_user_scope(request.user)
    return render(
        request,
        "reports/reports_dashboard.html",
        {
            "reports_list": available_reports,
            "user_scope": scope,
        },
    )


@login_required
def report_detail(request, slug: str):
    """عرض أي تقرير من التقارير الاثني عشر في صفحة مستقلة مع فلاتر وتصدير Excel/PDF وطباعة A4."""
    if slug not in REPORT_MAP:
        raise Http404("التقرير المطلوب غير موجود.")

    definition = REPORT_MAP[slug]
    error_message = None
    report_payload = None

    try:
        report_payload = build_report(slug, request.user, request.GET)
    except PermissionDenied:
        raise
    except ValidationError as exc:
        error_message = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        # إعادة بناء التقرير بدون الفلاتر الخاطئة لعرض الصفحة مع رسالة الخطأ الواضحة
        report_payload = build_report(slug, request.user, {})

    if request.GET.get("export") == "xlsx" and not error_message:
        return export_report_excel_response(report_payload)

    if request.GET.get("export") == "pdf" and not error_message:
        cols = report_payload["columns"]
        row_lines = [
            " | ".join(f"{c['label']}: {r.get(c['key'], '-')}" for c in cols[:6])
            for r in report_payload["rows"][:80]
        ]
        kpi_lines = [f"{k['label']}: {k['value']}" for k in report_payload.get("kpis", [])]
        pdf_bytes = build_institutional_pdf_bytes(
            title=f"Report: {definition.title}",
            subtitle=definition.subtitle,
            metadata_rows=[
                ("Generated At", report_payload["generated_at"].strftime("%Y-%m-%d %H:%M")),
                ("Total Rows", str(len(report_payload["rows"]))),
            ],
            sections=[
                {"heading": "KPIs Summary", "lines": kpi_lines or ["-"]},
                {"heading": "Report Data", "lines": row_lines or ["No matching rows."]},
            ],
        )
        return pdf_http_response(pdf_bytes, f"report_{slug}.pdf", inline=request.GET.get("inline") == "1")

    template_name = (
        "reports/report_print.html"
        if request.GET.get("print") == "1" and not error_message
        else "reports/report_detail.html"
    )
    return render(
        request,
        template_name,
        {
            "definition": definition,
            "report": report_payload,
            "error_message": error_message,
            "available_reports": get_available_reports_for_user(request.user),
            "query_params": {
                "date_from": request.GET.get("date_from", ""),
                "date_to": request.GET.get("date_to", ""),
                "sector": request.GET.get("sector", ""),
                "transaction_type": request.GET.get("transaction_type", ""),
            },
        },
    )
