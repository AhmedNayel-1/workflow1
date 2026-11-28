"""
مولد PDF مؤسسي مباشر متوافق مع المعيار %PDF-1.4 للتصدير والطباعة المؤسسية الفورية.
يدعم التصدير المباشر للموضوعات، المستندات، المذكرات، والتقارير الإدارية من الخادم.
"""
from __future__ import annotations

import re
from typing import Iterable, Tuple
from django.http import HttpResponse


def _encode_pdf_utf16_hex(text: str) -> str:
    raw = text.encode("utf-16-be")
    return "<FEFF" + raw.hex().upper() + ">"


def _ascii_safe_line(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    ascii_only = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in cleaned)
    ascii_only = re.sub(r"\s+", " ", ascii_only).strip()
    if not ascii_only:
        ascii_only = "[Arabic Institutional Record]"
    return ascii_only.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_institutional_pdf_bytes(
    title: str,
    subtitle: str = "",
    metadata_rows: Iterable[Tuple[str, str]] = (),
    sections: Iterable[dict] = (),
    institution_name: str = "West Delta Electricity Production Co. (WDEPCO) / EEHC",
) -> bytes:
    """بناء مستند PDF-1.4 متعدد الصفحات نظيف وصالح للقراءة والطباعة الفورية."""
    lines: list[tuple[str, int, bool]] = []
    lines.append((institution_name, 13, True))
    lines.append((title, 12, True))
    if subtitle:
        lines.append((subtitle, 10, False))
    lines.append(("------------------------------------------------------------------------", 9, False))

    for k, v in metadata_rows:
        lines.append((f"{k}: {v}", 10, False))

    for sec in sections:
        sec_heading = sec.get("heading", "")
        if sec_heading:
            lines.append(("", 8, False))
            lines.append((f"[ {sec_heading} ]", 11, True))
        for item in sec.get("lines", []):
            lines.append((str(item), 10, False))

    # تقسيم السطور إلى صفحات A4 (595 x 842 pt)
    max_lines_per_page = 42
    pages = [lines[i : i + max_lines_per_page] for i in range(0, max(1, len(lines)), max_lines_per_page)]

    objects: list[bytes] = []

    def add_obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog_id = add_obj(b"")  # placeholder 1
    pages_id = add_obj(b"")    # placeholder 2
    font_regular_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold_id = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    page_ids: list[int] = []
    for p_idx, page_lines in enumerate(pages, start=1):
        stream_cmds = ["BT"]
        y = 795
        for text_val, size, bold in page_lines:
            font_ref = "/F2" if bold else "/F1"
            safe_txt = _ascii_safe_line(text_val)[:95]
            stream_cmds.append(f"{font_ref} {size} Tf")
            stream_cmds.append(f"1 0 0 1 42 {y} Tm ({safe_txt}) Tj")
            y -= max(14, size + 5)
        stream_cmds.append(f"/F1 9 Tf 1 0 0 1 42 30 Tm (Page {p_idx} of {len(pages)} - Official Institutional Export) Tj")
        stream_cmds.append("ET")
        stream_bytes = "\n".join(stream_cmds).encode("latin-1", errors="replace")

        content_id = add_obj(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"\nendstream"
        )
        page_id = add_obj(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        page_ids.append(page_id)

    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids_str}] >>".encode("ascii")
    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")

    info_id = add_obj(
        (
            f"<< /Title {_encode_pdf_utf16_hex(title)} "
            f"/Subject {_encode_pdf_utf16_hex(subtitle or title)} "
            f"/Producer {_encode_pdf_utf16_hex(institution_name)} >>"
        ).encode("ascii")
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, obj_bytes in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(obj_bytes)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


def pdf_http_response(pdf_bytes: bytes, filename: str, inline: bool = False) -> HttpResponse:
    disposition = "inline" if inline else "attachment"
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename) or "export.pdf"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    resp["Content-Disposition"] = f'{disposition}; filename="{safe_name}"'
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "no-store, private"
    return resp
