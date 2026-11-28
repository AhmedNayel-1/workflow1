"""
تصدير التقارير الإدارية إلى ملفات Excel (.xlsx) احترافية عبر openpyxl
بالتنسيق العربي الكامل RTL وأوراق عمل مستقلة وتنسيق الأرقام والتواريخ وعرض الأعمدة.
"""
from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


def _sanitize_sheet_title(title: str) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]", " ", title).strip()
    return (cleaned[:31] or "تقرير").strip()


def render_report_excel_bytes(report_payload: dict[str, Any]) -> bytes:
    """بناء مصنف Excel كامل جاهز للتحميل أو الحفظ."""
    definition = report_payload["definition"]
    filters = report_payload["filters"]
    generated_at = report_payload["generated_at"]
    columns = report_payload["columns"]
    rows = report_payload["rows"]
    kpis = report_payload.get("kpis", [])

    wb = Workbook()
    ws = wb.active
    ws.title = _sanitize_sheet_title(definition.title)
    ws.views.sheetView[0].rightToLeft = True
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE if len(columns) >= 7 else ws.ORIENTATION_PORTRAIT
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    col_count = max(1, len(columns))
    last_col_letter = get_column_letter(col_count)

    thin_side = Side(style="thin", color="D0D7DE")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    title_font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
    title_fill = PatternFill(start_color="0B57D0", end_color="0B57D0", fill_type="solid")
    meta_font = Font(name="Arial", size=10, bold=False, color="1F1F1F")
    meta_fill = PatternFill(start_color="F2F6FC", end_color="F2F6FC", fill_type="solid")
    kpi_font = Font(name="Arial", size=10, bold=True, color="041E49")
    kpi_fill = PatternFill(start_color="E8F0FE", end_color="E8F0FE", fill_type="solid")
    header_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    body_font = Font(name="Arial", size=10, color="1F1F1F")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    # صف 1: العنوان الرئيسي
    ws.merge_cells(f"A1:{last_col_letter}1")
    ws["A1"] = f"منظومة السكرتارية والدورة المستندية — {definition.title}"
    ws["A1"].font = title_font
    ws["A1"].fill = title_fill
    ws["A1"].alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[1].height = 28

    # صف 2: معايير الفلترة وتاريخ الإصدار
    filter_parts = [f"تاريخ الاستخراج: {generated_at.strftime('%Y-%m-%d %H:%M')}"]
    if filters.date_from:
        filter_parts.append(f"من: {filters.date_from:%Y-%m-%d}")
    if filters.date_to:
        filter_parts.append(f"إلى: {filters.date_to:%Y-%m-%d}")
    if filters.sector:
        filter_parts.append(f"القطاع: {filters.sector.name}")
    else:
        filter_parts.append("القطاع: كل المتاح بصلاحياتك")
    if filters.transaction_type:
        filter_parts.append(f"نوع المعاملة: {filters.transaction_type.name}")

    ws.merge_cells(f"A2:{last_col_letter}2")
    ws["A2"] = " | ".join(filter_parts)
    ws["A2"].font = meta_font
    ws["A2"].fill = meta_fill
    ws["A2"].alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[2].height = 20

    # صف 3: ملخص المؤشرات (KPIs)
    kpi_summary = "   |   ".join(f"{k['label']}: {k['value']}" for k in kpis) if kpis else definition.subtitle
    ws.merge_cells(f"A3:{last_col_letter}3")
    ws["A3"] = kpi_summary
    ws["A3"].font = kpi_font
    ws["A3"].fill = kpi_fill
    ws["A3"].alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
    ws.row_dimensions[3].height = 22

    # صف 5: رؤوس الأعمدة
    header_row_idx = 5
    ws.row_dimensions[header_row_idx].height = 24
    col_widths = [max(14, len(col["label"]) + 6) for col in columns]

    for c_idx, col in enumerate(columns, start=1):
        cell = ws.cell(row=header_row_idx, column=c_idx, value=col["label"])
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = cell_border

    # بيانات الجدول
    if rows:
        for r_offset, row in enumerate(rows, start=1):
            r_idx = header_row_idx + r_offset
            use_zebra = (r_offset % 2 == 0)
            for c_idx, col in enumerate(columns, start=1):
                val = row.get(col["key"], "")
                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                cell.font = body_font
                cell.border = cell_border
                if use_zebra:
                    cell.fill = zebra_fill

                col_type = col.get("type", "text")
                if col_type == "number":
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    if isinstance(val, int):
                        cell.number_format = "#,##0"
                    elif isinstance(val, float):
                        cell.number_format = "#,##0.00"
                elif col_type in {"date", "link"}:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)

                val_len = len(str(val or "")) + 4
                if val_len > col_widths[c_idx - 1]:
                    col_widths[c_idx - 1] = min(48, val_len)
    else:
        empty_row = header_row_idx + 1
        ws.merge_cells(f"A{empty_row}:{last_col_letter}{empty_row}")
        ws[f"A{empty_row}"] = "لا توجد بيانات مطابقة لمعايير التصفية المحددة ضمن نطاق صلاحياتك."
        ws[f"A{empty_row}"].font = meta_font
        ws[f"A{empty_row}"].alignment = Alignment(horizontal="center", vertical="center")

    for c_idx, width in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(c_idx)].width = width

    ws.freeze_panes = f"A{header_row_idx + 1}"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_report_excel_response(report_payload: dict[str, Any]) -> HttpResponse:
    """إرجاع استجابة HTTP لتنزيل ملف Excel التقرير المحدد."""
    slug = report_payload["definition"].slug
    content = render_report_excel_bytes(report_payload)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = f"report_{slug}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
