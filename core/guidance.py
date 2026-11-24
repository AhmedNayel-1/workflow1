"""إرشاد لوحة «مهامي»: يقترح على المستخدم أين يبدأ يومه بحسب أعداد عمله."""
from django.urls import reverse


def build_dashboard_guidance(tab_counts: dict) -> dict:
    home = reverse("core:dashboard")
    overdue = int(tab_counts.get("overdue") or 0)
    primary = int(tab_counts.get("primary") or 0)
    tasks = int(tab_counts.get("tasks") or 0)
    readonly = int(tab_counts.get("readonly") or 0)

    def link(label, tab):
        return {"kind": "link", "label": label, "href": f"{home}?folder=inbox&tab={tab}"}

    new_subject = {"kind": "compose", "label": "موضوع جديد"}
    archive = {"kind": "link", "label": "البحث في الأرشيف", "href": reverse("core:archive_search")}

    if overdue:
        return {
            "tone": "danger", "eyebrow": "يحتاج انتباهك الآن",
            "title": f"لديك {overdue} موضوع متأخر أو عاجل",
            "text": "ابدأ بالمتأخر قبل غيره؛ كل موضوع يفتح لك فيه إجراء واضح للخطوة التالية.",
            "primary": link("ابدأ بالمتأخر", "overdue"),
            "secondary": ([link(f"عهدتي ({primary})", "primary")] if primary else []) + ([link(f"المهام ({tasks})", "tasks")] if tasks else []),
        }
    if primary:
        return {
            "tone": "primary", "eyebrow": "ابدأ يومك من هنا",
            "title": f"لديك {primary} موضوع في عهدتك",
            "text": "افتح أي موضوع وسيقترح عليك النظام الخطوة التالية بحسب مرحلته وصلاحياتك.",
            "primary": link("عرض مواضيع عهدتي", "primary"),
            "secondary": ([link(f"المهام ({tasks})", "tasks")] if tasks else []) + [new_subject],
        }
    if tasks:
        return {
            "tone": "primary", "eyebrow": "ابدأ يومك من هنا",
            "title": f"لديك {tasks} مهمة تنفيذية مفتوحة",
            "text": "راجع المهام المسندة إليك وأنجز الأقرب استحقاقاً.",
            "primary": link("عرض المهام", "tasks"),
            "secondary": [new_subject, archive],
        }
    return {
        "tone": "success", "eyebrow": "كل شيء تحت السيطرة",
        "title": "لا توجد مواضيع أو مهام عاجلة في عهدتك",
        "text": ("لديك %d موضوع للاطلاع والمتابعة فقط. " % readonly if readonly else "") + "يمكنك البدء بموضوع جديد أو البحث في الأرشيف.",
        "primary": new_subject,
        "secondary": ([link(f"للاطلاع ({readonly})", "readonly")] if readonly else []) + [archive],
    }
