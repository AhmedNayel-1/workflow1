"""
محلل ومعاين ملفات Office الداخلية (.docx / .xlsx / .pptx والنسخ الأقدم)
بدون الحاجة إلى LibreOffice أو خوادم خارجية، مع تعقيم HTML بالكامل للطباعة والمعاينة الفورية.
"""
from __future__ import annotations

import html
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _extract_docx_html(vault_path: Path) -> str:
    with zipfile.ZipFile(vault_path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return "<p>لا يوجد محتوى نصي قابل للعرض داخل ملف Word.</p>"
        root = ET.fromstring(zf.read("word/document.xml"))

    body = None
    for el in root:
        if _strip_ns(el.tag) == "body":
            body = el
            break
    if body is None:
        body = root

    parts: list[str] = ['<div class="office-docx-view space-y-2 text-sm leading-relaxed text-[#1F1F1F]" dir="auto">']
    for child in body:
        cname = _strip_ns(child.tag)
        if cname == "p":
            texts = [t.text for t in child.iter() if _strip_ns(t.tag) == "t" and t.text]
            para = "".join(texts).strip()
            if para:
                parts.append(f'<p class="py-1 border-b border-[#F1F3F4]/60">{html.escape(para)}</p>')
        elif cname == "tbl":
            parts.append('<div class="overflow-x-auto my-2"><table class="w-full border-collapse text-xs border border-[#DADCE0]">')
            for r_idx, row in enumerate(child):
                if _strip_ns(row.tag) != "tr":
                    continue
                parts.append("<tr>")
                for cell in row:
                    if _strip_ns(cell.tag) != "tc":
                        continue
                    cell_texts = [t.text for t in cell.iter() if _strip_ns(t.tag) == "t" and t.text]
                    cell_val = html.escape(" ".join(cell_texts).strip())
                    tag = "th" if r_idx == 0 else "td"
                    bg = "bg-[#F2F6FC] font-bold" if r_idx == 0 else "bg-white"
                    parts.append(f'<{tag} class="border border-[#DADCE0] px-2.5 py-1.5 text-right {bg}">{cell_val or "—"}</{tag}>')
                parts.append("</tr>")
            parts.append("</table></div>")
    parts.append("</div>")
    if len(parts) <= 2:
        return '<p class="text-xs text-[#5F6368]">المستند فارغ أو يحتوي على صور مضمنة فقط.</p>'
    return "".join(parts)


def _extract_xlsx_html(vault_path: Path) -> str:
    from openpyxl import load_workbook
    import io

    wb = load_workbook(filename=io.BytesIO(vault_path.read_bytes()), read_only=True, data_only=True)
    parts: list[str] = ['<div class="office-xlsx-view space-y-4 text-xs" dir="auto">']
    for sheet_name in wb.sheetnames[:8]:
        ws = wb[sheet_name]
        parts.append(f'<div class="border border-[#DADCE0] rounded-xl overflow-hidden bg-white">')
        parts.append(f'<div class="px-3 py-2 bg-[#F2F6FC] font-bold text-[#0B57D0] border-b border-[#DADCE0]">ورقة: {html.escape(sheet_name)}</div>')
        parts.append('<div class="overflow-x-auto"><table class="w-full border-collapse">')
        row_count = 0
        for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
            if row_count >= 120:
                parts.append('<tr><td colspan="20" class="px-3 py-2 text-center text-[#5F6368]">... تم عرض أول 120 صفاً للمعاينة السريعة ...</td></tr>')
                break
            if not any(v is not None and str(v).strip() != "" for v in row):
                continue
            row_count += 1
            parts.append("<tr>")
            for val in row[:20]:
                tag = "th" if r_idx == 0 else "td"
                cls = "bg-[#F8FAFC] font-bold text-[#1F1F1F]" if r_idx == 0 else "text-[#444746]"
                txt = html.escape("" if val is None else str(val))
                parts.append(f'<{tag} class="border border-[#ECEFF1] px-2.5 py-1.5 text-right {cls}">{txt}</{tag}>')
            parts.append("</tr>")
        if row_count == 0:
            parts.append('<tr><td class="px-3 py-4 text-center text-[#5F6368]">ورقة عمل فارغة</td></tr>')
        parts.append("</table></div></div>")
    wb.close()
    parts.append("</div>")
    return "".join(parts)


def _extract_pptx_html(vault_path: Path) -> str:
    with zipfile.ZipFile(vault_path, "r") as zf:
        slide_names = sorted(
            [n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)],
            key=lambda s: int(re.findall(r"\d+", s)[-1]),
        )
        if not slide_names:
            return '<p class="text-xs text-[#5F6368]">لا توجد شرائح نصية قابلة للعرض داخل العرض التقديمي.</p>'
        parts = ['<div class="office-pptx-view space-y-3 text-xs" dir="auto">']
        for idx, sname in enumerate(slide_names[:30], start=1):
            root = ET.fromstring(zf.read(sname))
            texts = [t.text.strip() for t in root.iter() if _strip_ns(t.tag) == "t" and t.text and t.text.strip()]
            parts.append('<div class="p-3 rounded-xl border border-[#DADCE0] bg-white space-y-1.5">')
            parts.append(f'<div class="font-bold text-[#0B57D0] border-b border-[#ECEFF1] pb-1">شريحة {idx}</div>')
            if texts:
                for line in texts:
                    parts.append(f'<div class="text-[#1F1F1F]">{html.escape(line)}</div>')
            else:
                parts.append('<div class="text-[#5F6368]">شريحة تحتوي على عناصر رسومية</div>')
            parts.append("</div>")
        parts.append("</div>")
        return "".join(parts)


def extract_office_preview_html(vault_path: Path, filename: str) -> str:
    """استخراج معاينة HTML نظيفة ومعقمة لأي ملف Office."""
    ext = Path(filename or "").suffix.lower()
    try:
        if ext == ".docx":
            return _extract_docx_html(vault_path)
        if ext == ".xlsx":
            return _extract_xlsx_html(vault_path)
        if ext == ".pptx":
            return _extract_pptx_html(vault_path)
        # ملفات Office الأقدم (.doc / .xls / .ppt / .rtf)
        raw = vault_path.read_bytes()[:65536]
        decoded = raw.decode("utf-8", errors="ignore")
        printable = re.findall(r"[\u0600-\u06FF0-9A-Za-z\s\.,:\-_/()]{4,}", decoded)
        clean_lines = [html.escape(line.strip()) for line in printable[:60] if line.strip()]
        if clean_lines:
            joined = "".join(f'<p class="py-0.5">{ln}</p>' for ln in clean_lines)
            return f'<div class="space-y-1 text-xs text-[#1F1F1F]" dir="auto">{joined}</div>'
        return '<div class="p-4 text-xs text-[#5F6368]">ملف Office قديم ثنائي التنسيق — يمكنك طباعة بطاقة بياناته أو تنزيله مباشرة.</div>'
    except Exception as exc:
        return f'<div class="p-4 text-xs text-[#A50E0E]">تعذر تحليل معاينة ملف Office ({html.escape(str(exc))}). يمكنك تنزيل الملف أو طباعة بطاقته.</div>'
