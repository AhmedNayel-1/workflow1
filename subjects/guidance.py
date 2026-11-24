"""
محرك الإرشاد: يحدد «الخطوة التالية» المناسبة للمستخدم داخل صفحة الموضوع
حسب حالة الموضوع وصلاحيات المستخدم، ويعيد خياراً رئيسياً واحداً وخيارات بديلة محدودة.

كل إجراء عبارة عن قاموس:
    kind  : link | jump | post | compose
    label : نص الزر
    href  : للنوع link و post (رابط الوجهة)
    target: للنوع jump (معرّف القسم داخل الصفحة)
    fields: للنوع post (حقول مخفية إضافية مثل action)
"""
from django.urls import reverse


def _link(label, href):
    return {"kind": "link", "label": label, "href": href}


def _jump(label, target):
    return {"kind": "jump", "label": label, "target": target}


def _post(label, href, **fields):
    return {"kind": "post", "label": label, "href": href, "fields": fields}


def build_subject_guidance(
    subject,
    perms: dict,
    *,
    pending_recipient=None,
    has_memo: bool = False,
    decisions_count: int = 0,
    referrals_count: int = 0,
    docs_count: int = 0,
    closure_blockers=None,
    active_step: int = 2,
    is_closed: bool = False,
) -> dict:
    """يعيد dict يحتوي: tone, eyebrow, title, text, primary, secondary."""
    closure_blockers = list(closure_blockers or [])
    export_pdf = _link("تصدير PDF", reverse("subjects:subject_export_pdf", args=[subject.id]))
    timeline = _jump("السجل الزمني", "sec-timeline")
    overdue = bool(getattr(subject, "is_overdue", False))
    overdue_note = " والموضوع متأخر عن موعد استحقاقه، فيُفضّل البدء به أولاً." if overdue else ""

    # 1) إحالة بانتظار المستخدم — لها الأولوية القصوى
    if pending_recipient is not None:
        respond = reverse("workflow:referral_respond", args=[pending_recipient.id])
        return {
            "tone": "warning",
            "eyebrow": "بانتظار إجراء منك",
            "title": "وصلتك إحالة على هذا الموضوع",
            "text": "ابدأ بتأكيد الاستلام ليعرف المُحيل أنك اطلعت عليها، ثم أتمم الرد عند الانتهاء." + overdue_note,
            "primary": _post("تأكيد الاستلام", respond, action="acknowledge"),
            "secondary": [
                _post("إتمام الرد", respond, action="complete"),
                _jump("عرض الإحالات", "sec-referrals"),
                export_pdf,
            ],
        }

    # 2) موضوع مغلق
    if is_closed or subject.status == "CLOSED":
        secondary = [export_pdf, timeline]
        if perms.get("can_reopen"):
            secondary.insert(0, _jump("إعادة فتح الموضوع", "sec-closure"))
        return {
            "tone": "success",
            "eyebrow": "اكتمل المسار",
            "title": "الموضوع مغلق ومؤرشف",
            "text": "لا توجد إجراءات مطلوبة. يمكنك مراجعة السجل الزمني أو تصدير نسخة PDF للأرشيف.",
            "primary": _jump("مراجعة السجل الزمني", "sec-timeline"),
            "secondary": secondary[:3],
        }

    # 3) وضع الاطلاع فقط
    if not perms.get("can_act"):
        return {
            "tone": "info",
            "eyebrow": "وضع الاطلاع",
            "title": "هذا الموضوع متاح لك للاطلاع والمتابعة فقط",
            "text": "يمكنك قراءة المستندات والسجل الزمني، أما الإجراءات فتتم عبر المسؤول عن الموضوع حالياً.",
            "primary": _jump("عرض المستندات", "sec-documents"),
            "secondary": [timeline, export_pdf],
        }

    # 4) موضوع معلّق لاستيفاء مستندات
    if subject.status == "SUSPENDED":
        return {
            "tone": "warning",
            "eyebrow": "الموضوع معلّق",
            "title": "المطلوب استيفاء مستندات ليُستأنف العمل",
            "text": "أرفق المستند المطلوب ثم أنهِ التعليق من قسم التأشيرات والإغلاق." + overdue_note,
            "primary": _jump("إرفاق المستند المطلوب", "sec-documents"),
            "secondary": [_jump("إنهاء التعليق", "sec-closure"), timeline],
        }

    refer_url = reverse("workflow:referral_create", args=[subject.id])
    decision_url = reverse("decisions:decision_create", args=[subject.id])
    secondary = []

    # 5) لا توجد مستندات بعد
    if docs_count == 0 and perms.get("can_act"):
        primary = _jump("إرفاق أول مستند", "sec-documents")
        title, text = "ابدأ بإرفاق مستندات الموضوع", "الموضوع بلا مرفقات حتى الآن. أرفق الأصل أو الصورة الممسوحة ليسهل على الجميع المراجعة."
        if perms.get("can_refer"):
            secondary.append(_link("إحالة الموضوع الآن", refer_url))
        eyebrow = "الخطوة التالية"
    # 6) التوجيه والإحالة
    elif active_step <= 3 and perms.get("can_refer"):
        if active_step == 2 and referrals_count == 0:
            title = "وجّه الموضوع إلى الجهة المعنية"
            text = "لم تتم أي إحالة بعد. اختر المستلم (مدير عام أو قسم أو موظف مختص) وحدّد نوع الإحالة."
        else:
            title = "وزّع الموضوع على القسم أو الموظف المختص"
            text = "تمت الإحالة للمستوى الأعلى. الخطوة التالية تكليف من سينفذ ويدرس الموضوع."
        eyebrow = "الخطوة التالية"
        primary = _link("إحالة الموضوع", refer_url)
        text += overdue_note
        if perms.get("can_memo"):
            secondary.append(_jump("إعداد مذكرة", "sec-memos"))
    # 7) إعداد المذكرة والقرار
    elif active_step == 4 or (active_step <= 4 and not perms.get("can_refer")):
        eyebrow = "الخطوة التالية"
        if not has_memo and perms.get("can_memo"):
            title, text = "أعدّ مذكرة العرض والرأي", "المذكرة تلخّص الموضوع وتوصيتك لصاحب القرار. بعد اعتمادها يمكن إعداد القرار."
            primary = _jump("إعداد المذكرة", "sec-memos")
            if perms.get("can_decide"):
                secondary.append(_link("إعداد قرار إداري", decision_url))
        elif perms.get("can_decide") and decisions_count == 0:
            title, text = "حان وقت القرار", "المذكرة جاهزة. أعدّ القرار الإداري ليُعتمد ويُوزّع على الجهات المنفذة."
            primary = _link("إعداد قرار إداري", decision_url)
            if perms.get("can_approve"):
                secondary.append(_jump("اعتماد المذكرة", "sec-memos"))
        elif perms.get("can_approve") and has_memo:
            title, text = "راجع المذكرة واعتمدها", "هناك مذكرة تنتظر الاعتماد لينتقل الموضوع للمرحلة التالية."
            primary = _jump("مراجعة المذكرات", "sec-memos")
        else:
            title, text = "الموضوع قيد الدراسة والتنفيذ", "تابع المهام والقرارات المرتبطة، وأضف تأشيرة أو مستنداً إن لزم."
            primary = _jump("المهام والقرارات", "sec-tasks")
        text += overdue_note
    # 8) الاعتماد والإغلاق
    else:
        eyebrow = "الخطوة الأخيرة"
        if perms.get("can_close"):
            if closure_blockers:
                title = "أنجز الملاحظات قبل إغلاق الموضوع"
                text = f"توجد {len(closure_blockers)} ملاحظة تمنع الإغلاق الآن، وهي موضحة في قسم الإغلاق."
                primary = _jump("عرض ملاحظات الإغلاق", "sec-closure")
            else:
                title, text = "الموضوع جاهز للإغلاق والأرشفة", "استوفى المتطلبات. أضف ملاحظات الإغلاق إن رغبت ثم أغلقه ليُؤرشف."
                primary = _jump("إغلاق الموضوع وأرشفته", "sec-closure")
        else:
            title, text = "بانتظار استكمال بقية الإجراءات", "لا يوجد إجراء مطلوب منك الآن. تابع الإحالات والمهام."
            primary = _jump("متابعة الإحالات", "sec-referrals")

    # خيارات بديلة إضافية بحسب الصلاحية (بحد أقصى 4)
    if perms.get("can_annotate"):
        secondary.append(_jump("إضافة تأشيرة", "sec-closure"))
    if perms.get("can_suspend"):
        secondary.append(_jump("تعليق لاستيفاء مستندات", "sec-closure"))
    secondary += [timeline, export_pdf]

    seen, unique = {primary["label"]}, []
    for act in secondary:
        if act["label"] not in seen:
            seen.add(act["label"])
            unique.append(act)

    return {
        "tone": "danger" if overdue else "primary",
        "eyebrow": eyebrow,
        "title": title,
        "text": text,
        "primary": primary,
        "secondary": unique[:4],
    }
