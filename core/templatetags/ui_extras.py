"""فلاتر مساعدة للواجهة الجديدة."""
from django import template

register = template.Library()

_TONES = {
    # موضوعات
    "NEW": "info", "INCOMING": "info", "UNDER_REVIEW": "warn", "IN_PROGRESS": "brand",
    "AWAITING_APPROVAL": "warn", "AWAITING_COMMITTEE": "warn", "SUSPENDED": "bad",
    "DECISION_ISSUED": "ok", "DISTRIBUTING": "brand", "FINAL_EXECUTION": "brand",
    "COMPLETED": "ok", "CLOSED": "mute", "REOPENED": "warn", "REJECTED": "bad", "CANCELLED": "mute",
    # قرارات
    "DRAFT": "mute", "APPROVED": "ok", "ISSUED": "ok", "EXECUTING": "brand",
    # إحالات
    "PENDING": "warn", "RECEIVED": "info", "RESPONDED": "ok", "RETURNED": "bad", "WAITING_TURN": "mute",
    "VIEWED_ONLY": "info", "SKIPPED_NO_RESPONSE": "mute", "WITHDRAWN": "mute",
    # مهام
    "OPEN": "info", "DONE": "ok", "SUCCESS": "ok", "DENIED": "bad", "FAILURE": "bad", "ERROR": "bad",
}


@register.filter
def tone(value):
    """يحوّل كود حالة إلى لون: ok / warn / bad / info / brand / mute."""
    return _TONES.get(str(value or "").upper(), "mute")


@register.filter
def initials(value):
    text = (str(value or "").strip()) or "؟"
    parts = text.split()
    if len(parts) >= 2:
        return (parts[0][:1] + parts[1][:1])
    return text[:2]


@register.filter
def fsize(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def short(value, n=60):
    s = str(value or "")
    n = int(n)
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------- الأيقونات
from django.utils.html import format_html  # noqa: E402
from django.utils.safestring import mark_safe  # noqa: E402

_ICONS = {
    "home": '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/>',
    "send": '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
    "archive": '<rect x="3" y="3" width="18" height="5" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8"/><path d="M10 12h4"/>',
    "share": '<path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
    "task": '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/>',
    "gavel": '<path d="M14 13l-8.5 8.5a2.1 2.1 0 0 1-3-3L11 10"/><path d="M16 16l6-6"/><path d="M8 8l6-6"/><path d="M9 7l8 8"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
    "usercheck": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M16 11l2 2 4-4"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    "filter": '<path d="M22 3H2l8 9.5V19l4 2v-8.5z"/>',
    "chart": '<path d="M18 20V10M12 20V4M6 20v-6"/>',
    "flow": '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="M6 9v3a3 3 0 0 0 3 3h6"/>',
    "tree": '<rect x="9" y="2" width="6" height="5" rx="1"/><rect x="2" y="17" width="6" height="5" rx="1"/><rect x="16" y="17" width="6" height="5" rx="1"/><path d="M12 7v5M5 17v-5h14v5"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>',
    "cog": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "db": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.7-4 3-9 3s-9-1.3-9-3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/>',
    "help": '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "menu": '<path d="M3 6h18M3 12h18M3 18h18"/>',
    "panel": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M15 3v18"/>',
    "chevl": '<path d="M15 18l-6-6 6-6"/>', "chevr": '<path d="M9 18l6-6-6-6"/>', "chevd": '<path d="M6 9l6 6 6-6"/>',
    "x": '<path d="M18 6L6 18M6 6l12 12"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/>',
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    "print": '<path d="M6 9V2h12v7"/><rect x="6" y="14" width="12" height="8"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "clip": '<path d="M21.4 11l-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "alert": '<path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "checkc": '<path d="M22 11.1V12a10 10 0 1 1-5.9-9.1"/><path d="M22 4L12 14l-3-3"/>',
    "more": '<circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>',
    "ext": '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14L21 3"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5V22h16"/>',
    "spark": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>',
    "note": '<path d="M4 4h16v12l-4 4H4z"/><path d="M16 20v-4h4"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    "sort": '<path d="M7 4v16M3 16l4 4 4-4M17 20V4M13 8l4-4 4 4"/>',
    "refresh": '<path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15"/>',
}


@register.simple_tag
def icon(name, cls=""):
    path = _ICONS.get(name, _ICONS["info"])
    return mark_safe(
        f'<svg class="icon {cls}" viewBox="0 0 24 24" aria-hidden="true">{path}</svg>'
    )


@register.simple_tag
def pairget(mapping, a, b):
    """يجلب عنصراً من قاموس مفاتيحه أزواج (tuple)."""
    try:
        return mapping.get((a, b))
    except AttributeError:
        return None


@register.simple_tag
def qs(request, exclude="page"):
    """يعيد معاملات GET الحالية مرمّزة ومنتهية بـ & بدون معامل الصفحة، لاستخدامها في روابط الترقيم."""
    from urllib.parse import urlencode

    skip = {x.strip() for x in str(exclude).split(",")}
    items = [(k, v) for k in request.GET for v in request.GET.getlist(k) if k not in skip and v != ""]
    out = urlencode(items)
    return (out + "&") if out else ""


@register.filter
def arstatus(value):
    """Display only: show known subject status codes written as (CODE) with their canonical Arabic label. Unknown codes stay as they are."""
    import re
    from subjects.models import Subject
    labels = dict(Subject.Status.choices)
    return re.sub(r"\(([A-Z_]+)\)", lambda m: "(%s)" % labels[m.group(1)] if m.group(1) in labels else m.group(0), str(value or ""))


_NOTIF_CAT_AR = {
    "INCOMING_REFERRAL": "إحالة واردة", "REFERRAL": "إحالة واردة",
    "DECISION_TASK": "قرار / مهمة", "DECISION": "قرار", "TASK": "مهمة",
    "DEADLINE": "موعد", "ESCALATION_OVERDUE": "تصعيد / تأخير",
    "SUSPENSION": "تعليق / استيفاء", "REPLY_MEMO": "رد / مذكرة",
    "FULFILLMENT": "استيفاء", "APPROVAL_NEEDED": "بانتظار اعتماد",
}
_LEVEL_AR = {"EXECUTIVE": "تنفيذي", "MANAGER": "إداري", "STAFF": "موظف"}


@register.filter
def notif_cat_ar(value):
    """Presentation only: Arabic label for a notification category code."""
    return _NOTIF_CAT_AR.get(value, value)


@register.filter
def perm_name_ar(code):
    """Presentation only: Arabic name of a permission code (falls back to the code)."""
    from accounts.models import PermissionCode
    cache = getattr(perm_name_ar, "_c", None)
    import time
    if cache is None or time.time() - cache[0] > 30:
        cache = (time.time(), dict(PermissionCode.objects.values_list("code", "name")))
        perm_name_ar._c = cache
    return cache[1].get(code, code)


@register.filter
def split(value, sep=","):
    """تقسيم نص إلى قائمة (لمحدد حجم الصفحة)."""
    return str(value).split(sep)
