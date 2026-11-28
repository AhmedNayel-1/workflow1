"""
نموذج الموضوع الرئيسي (منفصل عن المستند والمهمة)، مع إدارة التعليق والاستيفاء،
المذكرات، التأشيرات، صلاحيات الاستثناء على الموضوع، واكتشاف تعارض التعديل المتزامن.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Subject(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "جديد"
        INCOMING = "INCOMING", "وارد"
        UNDER_REVIEW = "UNDER_REVIEW", "قيد المراجعة"
        IN_PROGRESS = "IN_PROGRESS", "قيد التنفيذ"
        AWAITING_APPROVAL = "AWAITING_APPROVAL", "في انتظار اعتماد"
        AWAITING_COMMITTEE = "AWAITING_COMMITTEE", "في انتظار لجنة"
        SUSPENDED = "SUSPENDED", "معلق (للاستيفاء)"
        DECISION_ISSUED = "DECISION_ISSUED", "صدر القرار"
        DISTRIBUTING = "DISTRIBUTING", "قيد التوزيع"
        FINAL_EXECUTION = "FINAL_EXECUTION", "قيد التنفيذ النهائي"
        COMPLETED = "COMPLETED", "مكتمل"
        CLOSED = "CLOSED", "مغلق"
        REOPENED = "REOPENED", "أُعيد فتحه"
        REJECTED = "REJECTED", "مرفوض"
        CANCELLED = "CANCELLED", "ملغى"

    class RetentionStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "نشط"
        ARCHIVED = "ARCHIVED", "مؤرشف"
        HOLD = "HOLD", "موقوف عن الإتلاف"
        UNDER_REVIEW = "UNDER_REVIEW", "خاضع لمراجعة"
        RETENTION_EXPIRED = "RETENTION_EXPIRED", "منتهي مدة الاحتفاظ وفق السياسة"

    internal_number = models.CharField("الرقم الداخلي للموضوع", max_length=40, unique=True, db_index=True)
    title = models.CharField("عنوان الموضوع", max_length=255)
    description = models.TextField("ملخص وتفاصيل الموضوع", blank=True)
    transaction_type = models.ForeignKey(
        "core.TransactionType",
        on_delete=models.PROTECT,
        verbose_name="نوع المعاملة",
    )
    sector = models.ForeignKey(
        "organization.Sector",
        on_delete=models.PROTECT,
        verbose_name="القطاع المختص",
    )
    org_unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.PROTECT,
        verbose_name="الوحدة التنظيمية المعنية",
    )
    applicant_name = models.CharField("مقدم الطلب / صاحب الشأن", max_length=180, blank=True)
    external_source = models.CharField("الجهة الواردة", max_length=180, blank=True)

    class OriginType(models.TextChoices):
        INTERNAL = "INTERNAL", "داخلي"
        EXTERNAL = "EXTERNAL", "خارجي"

    origin_type = models.CharField("نوع جهة الورود", max_length=10, choices=OriginType.choices, blank=True, db_index=True)
    origin_unit = models.ForeignKey(
        "organization.OrgUnit", on_delete=models.PROTECT, null=True, blank=True,
        related_name="origin_subjects", verbose_name="الجهة الداخلية (مُكوَّدة)",
    )
    origin_external = models.ForeignKey(
        "organization.ExternalEntity", on_delete=models.PROTECT, null=True, blank=True,
        related_name="origin_subjects", verbose_name="الجهة الخارجية (مُكوَّدة)",
    )
    incoming_number = models.CharField("رقم الوارد في السجل الورقي", max_length=60, blank=True, db_index=True)
    received_date = models.DateField("تاريخ الاستلام", null=True, blank=True)
    direction = models.CharField("اتجاه المعاملة", max_length=3, blank=True, db_index=True, help_text="IN وارد، OUT صادر، فارغ لسجلات قديمة")
    outgoing_auto_number = models.CharField("رقم الصادر (النظام)", max_length=40, blank=True, db_index=True)
    outgoing_paper_number = models.CharField("رقم الصادر في الورقة", max_length=60, blank=True, db_index=True)
    sent_date = models.DateField("تاريخ الإرسال", null=True, blank=True)
    signer_name = models.CharField("اسم الموقّع على الورقة", max_length=180, blank=True)
    confidentiality = models.ForeignKey(
        "core.ConfidentialityLevel",
        on_delete=models.PROTECT,
        verbose_name="درجة السرية",
    )
    priority = models.ForeignKey(
        "core.PriorityLevel",
        on_delete=models.PROTECT,
        verbose_name="الأولوية",
    )
    due_date = models.DateField("تاريخ الاستحقاق المحدد", null=True, blank=True, db_index=True)
    status = models.CharField("الحالة الحالية", max_length=30, choices=Status.choices, default=Status.NEW)
    current_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_subjects",
        verbose_name="المسؤول عن المتابعة",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_subjects",
        verbose_name="منشئ الموضوع",
    )
    workflow_template_version = models.ForeignKey(
        "workflow.WorkflowTemplateVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="إصدار قالب المسار",
    )
    retention_policy = models.ForeignKey(
        "core.RetentionPolicy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="سياسة الاحتفاظ",
    )
    retention_status = models.CharField(
        "حالة الاحتفاظ",
        max_length=30,
        choices=RetentionStatus.choices,
        default=RetentionStatus.ACTIVE,
    )
    keywords = models.CharField("كلمات مفتاحية", max_length=255, blank=True)
    version_lock = models.PositiveIntegerField("رقم نسخة التزامن", default=1)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    last_action_at = models.DateTimeField("تاريخ آخر إجراء", auto_now_add=True)
    closed_at = models.DateTimeField("تاريخ الإغلاق", null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_subjects",
        verbose_name="أُغلق بواسطة",
    )
    closure_notes = models.TextField("ملاحظات / مبرر الإغلاق", blank=True)
    closure_outcome = models.CharField("نتيجة الإغلاق", max_length=255, blank=True)
    is_exceptional_closure = models.BooleanField("إغلاق استثنائي", default=False)

    class Meta:
        verbose_name = "موضوع"
        verbose_name_plural = "الموضوعات"
        ordering = ["-last_action_at", "-id"]
        indexes = [
            models.Index(fields=["status", "sector"]),
            models.Index(fields=["confidentiality", "org_unit"]),
            models.Index(fields=["status", "current_owner", "last_action_at"]),
            models.Index(fields=["due_date", "status"]),
            models.Index(fields=["sector", "org_unit"]),
        ]

    def __str__(self):
        return f"{self.internal_number} — {self.title}"

    @property
    def is_overdue(self) -> bool:
        if not self.due_date:
            return False
        if self.status == self.Status.SUSPENDED:
            return False
        if self.status in {self.Status.CLOSED, self.Status.COMPLETED, self.Status.CANCELLED, self.Status.REJECTED}:
            return False
        return self.due_date < timezone.localdate()

    @property
    def overdue_days(self) -> int:
        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.due_date).days


class SubjectAccessGrant(models.Model):
    """استثناءات الصلاحية المحددة لكل موضوع (منح صريح أو منع صريح)."""
    class AccessType(models.TextChoices):
        GRANT = "GRANT", "منح اطلاع صريح"
        DENY = "DENY", "منع صريح"

    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="access_grants",
        verbose_name="الموضوع",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name="المستخدم",
    )
    access_type = models.CharField("نوع الاستثناء", max_length=10, choices=AccessType.choices)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="granted_subject_accesses",
        verbose_name="بواسطة",
    )
    reason = models.CharField("السبب", max_length=255, blank=True)
    created_at = models.DateTimeField("التاريخ", auto_now_add=True)

    class Meta:
        verbose_name = "استثناء صلاحية موضوع"
        verbose_name_plural = "استثناءات صلاحيات الموضوعات"
        unique_together = [("subject", "user")]


class SubjectSuspension(models.Model):
    """سجل تعليق الموضوع والاستيفاء (التعليق لا يعني الإغلاق)."""
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="suspensions",
        verbose_name="الموضوع",
    )
    reason_ref = models.ForeignKey(
        "core.SuspensionReason",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="سبب التعليق المرجعي",
    )
    reason_details = models.TextField("تفاصيل سبب التعليق")
    required_from = models.CharField("الجهة أو الشخص المطلوب منه الاستيفاء", max_length=180)
    committee = models.ForeignKey(
        "committees.Committee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incoming_suspensions",
        verbose_name="اللجنة (اختياري)",
    )
    required_item = models.CharField("المستند أو الإجراء المطلوب", max_length=255)
    suspended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="suspended_subjects",
        verbose_name="تم التعليق بواسطة",
    )
    follow_up_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="suspension_follow_ups",
        verbose_name="المسؤول عن المتابعة",
    )
    suspended_at = models.DateTimeField("تاريخ التعليق", auto_now_add=True)
    expected_follow_up_date = models.DateField("تاريخ المتابعة المتوقع", null=True, blank=True)
    is_fulfilled = models.BooleanField("تم الاستيفاء", default=False)
    fulfilled_at = models.DateTimeField("تاريخ الاستيفاء", null=True, blank=True)
    fulfilled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fulfilled_suspensions",
        verbose_name="سُجّل الاستيفاء بواسطة",
    )
    fulfillment_notes = models.TextField("بيان ما تم تقديمه للاستيفاء", blank=True)

    class Meta:
        verbose_name = "سجل تعليق واستيفاء"
        verbose_name_plural = "سجلات التعليق والاستيفاء"
        ordering = ["-suspended_at"]


class SubjectStatusHistory(models.Model):
    """سجل تغيرات حالة الموضوع والاحتفاظ بحالة الإغلاق السابقة عند إعادة الفتح."""
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField("من حالة", max_length=30, blank=True)
    to_status = models.CharField("إلى حالة", max_length=30)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField("السبب / الملاحظة", blank=True)
    changed_at = models.DateTimeField("وقت التغيير", auto_now_add=True)

    class Meta:
        verbose_name = "سجل تغير حالة موضوع"
        verbose_name_plural = "سجل تغيرات حالات الموضوعات"
        ordering = ["-changed_at"]


class Memo(models.Model):
    """المذكرات الإدارية المرتبطة بالموضوع (عرض، رأي، استيفاء، عرض على لجنة، تنفيذ، إعادة عرض)."""
    class MemoType(models.TextChoices):
        PRESENTATION = "PRESENTATION", "مذكرة عرض"
        OPINION = "OPINION", "مذكرة رأي"
        FULFILLMENT = "FULFILLMENT", "مذكرة استيفاء"
        COMMITTEE = "COMMITTEE", "مذكرة للعرض على لجنة"
        EXECUTION = "EXECUTION", "مذكرة تنفيذ"
        RE_PRESENTATION = "RE_PRESENTATION", "مذكرة إعادة عرض"

    class MemoStatus(models.TextChoices):
        DRAFT = "DRAFT", "مسودة"
        APPROVED = "APPROVED", "معتمدة"

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="memos", verbose_name="الموضوع")
    memo_number = models.CharField("رقم المذكرة", max_length=40, unique=True)
    memo_type = models.CharField("نوع المذكرة", max_length=120, default=MemoType.PRESENTATION)
    title = models.CharField("عنوان المذكرة", max_length=255)
    directed_to = models.CharField("الجهة الموجه إليها", max_length=180)
    body = models.TextField("نص المذكرة")
    status = models.CharField("الحالة", max_length=20, choices=MemoStatus.choices, default=MemoStatus.DRAFT)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="معد المذكرة")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_memos",
        verbose_name="معتمد المذكرة",
    )
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)
    updated_at = models.DateTimeField("آخر تحديث", auto_now=True)

    class Meta:
        verbose_name = "مذكرة"
        verbose_name_plural = "المذكرات"
        ordering = ["-created_at"]

    def get_memo_type_display(self):
        enum_map = dict(self.MemoType.choices)
        if self.memo_type in enum_map:
            return enum_map[self.memo_type]
        from core.models import MemoTypeRef
        ref = MemoTypeRef.objects.filter(models.Q(code=self.memo_type) | models.Q(name=self.memo_type)).first()
        return ref.name if ref else self.memo_type

    def __str__(self):
        return f"{self.memo_number} — {self.title}"


class Annotation(models.Model):
    """
    التأشيرات الإدارية المسجلة على الموضوع/المستند.
    ملاحظة: التأشيرة توثيق لتوجيه المسؤول ولا تفترض توقيعاً إلكترونياً معتمداً قانونياً.
    """
    class ExecutionState(models.TextChoices):
        PENDING = "PENDING", "قيد المتابعة"
        IN_PROGRESS = "IN_PROGRESS", "جاري التنفيذ"
        DONE = "DONE", "تم التنفيذ"

    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="annotations",
        verbose_name="الموضوع",
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="المستند الصادرة عليه التأشيرة",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="annotations_written",
        verbose_name="صاحب التأشيرة",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="annotations_recorded",
        verbose_name="مسجل التأشيرة بالنظام",
    )
    annotation_text = models.TextField("نص التأشيرة")
    required_action = models.CharField("الإجراء المطلوب بعدها", max_length=255)
    assigned_unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="الجهة المكلفة",
    )
    execution_status = models.CharField(
        "حالة التنفيذ",
        max_length=20,
        choices=ExecutionState.choices,
        default=ExecutionState.PENDING,
    )
    class Outcome(models.TextChoices):
        PERSONNEL_COMMITTEE = "PERSONNEL_COMMITTEE", "عرض على لجنة شئون العاملين"
        GRIEVANCE_COMMITTEE = "GRIEVANCE_COMMITTEE", "عرض على لجنة التظلمات"
        VERBAL_NOTICE = "VERBAL_NOTICE", "إخطار شفهي"
        WRITTEN_NOTICE = "WRITTEN_NOTICE", "إخطار كتابي"
        REJECT = "REJECT", "رفض"
        RETURN_FOR_AMENDMENT = "RETURN_FOR_AMENDMENT", "إرجاع للتعديل"
        OTHER = "OTHER", "أخرى (يُكتب النص)"

    # اختياري: توصيف توجيه التأشيرة. لا يحدد مساراً ولا يفرض خطوة ولا يغيّر الصلاحيات؛ نص التأشيرة هو المرجع.
    outcome = models.CharField("نتيجة/توجيه التأشيرة", max_length=30, choices=Outcome.choices, blank=True, default="")
    outcome_other = models.CharField("توجيه آخر (نص حر)", max_length=255, blank=True, default="")
    annotation_date = models.DateTimeField("تاريخ التأشيرة", auto_now_add=True)

    class Meta:
        verbose_name = "تأشيرة إدارية"
        verbose_name_plural = "التأشيرات الإدارية"
        ordering = ["-annotation_date"]


class NoticeRecord(models.Model):
    """
    سجل إخطار فعلي لصاحب الشأن. يوثق أن الإخطار تم (وبأي وسيلة) بواسطة من سجله؛
    لا يُنشأ تلقائياً من نص التأشيرة، ولا يغيّر حالة الموضوع أو صلاحياته.
    """
    class Method(models.TextChoices):
        VERBAL = "VERBAL", "شفهي"
        WRITTEN = "WRITTEN", "كتابي"
        PHONE = "PHONE", "هاتفي"
        OTHER = "OTHER", "أخرى"

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="notice_records", verbose_name="الموضوع")
    annotation = models.ForeignKey(Annotation, on_delete=models.SET_NULL, null=True, blank=True, related_name="notice_records", verbose_name="التأشيرة المرتبطة")
    recipient_name = models.CharField("المُخطَر", max_length=255)
    method = models.CharField("وسيلة الإخطار", max_length=10, choices=Method.choices)
    method_other = models.CharField("وسيلة أخرى", max_length=120, blank=True, default="")
    notes = models.TextField("ملاحظات", blank=True, default="")
    notified_at = models.DateTimeField("وقت الإخطار")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="notice_records", verbose_name="سجّله")
    recorded_at = models.DateTimeField("وقت التسجيل", auto_now_add=True)

    class Meta:
        verbose_name = "سجل إخطار"
        verbose_name_plural = "سجلات الإخطار"
        ordering = ["-notified_at", "-id"]


class OutgoingCorrespondence(models.Model):
    """
    مراسلة صادرة مسجلة على الموضوع (النظام لا يرسل شيئاً لأي طرف خارجي؛ يوثق ما تم إرساله فعلاً).
    - REQUEST: طلب بيان/رد من جهة؛ يبقى الموضوع مفتوحاً بانتظار الرد حتى يُسجَّل الرد/الاستيفاء.
    - FOLLOWUP: استعجال مرتبط بطلب أصلي (parent) على نفس الموضوع؛ لا يغلق شيئاً ولا يحدد موعداً.
    - RESPONSE: رد صادر على طلب وارد (بيان وارد انتهى فخرج كصادر) ضمن نفس الموضوع؛ لا ينتظر رداً.
    """
    class Kind(models.TextChoices):
        REQUEST = "REQUEST", "طلب بيان/رد (بانتظار الرد)"
        FOLLOWUP = "FOLLOWUP", "استعجال"
        RESPONSE = "RESPONSE", "رد صادر على وارد"

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="outgoing_items", verbose_name="الموضوع")
    kind = models.CharField("النوع", max_length=10, choices=Kind.choices)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="followups", verbose_name="الطلب الأصلي")
    recipient_entity = models.CharField("الجهة", max_length=255)
    title = models.CharField("موضوع المراسلة", max_length=255)
    notes = models.TextField("ملاحظات", blank=True, default="")
    document = models.ForeignKey("documents.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="المستند الصادر")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="outgoing_recorded", verbose_name="سجّله")
    recorded_at = models.DateTimeField("وقت التسجيل", auto_now_add=True)
    is_origin = models.BooleanField("بدأ بها الموضوع", default=False)
    # مسودة/معدّة إن كان فارغاً؛ يُسجَّل بتأكيد بشري صريح بعد الإرسال الفعلي (النظام لا يرسل)
    sent_at = models.DateTimeField("وقت تسجيل الإرسال الفعلي", null=True, blank=True)
    sent_marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="outgoing_sent_marked", verbose_name="أكّد الإرسال")
    # للطلبات فقط
    reply_received_at = models.DateTimeField("وقت تسجيل الرد/الاستيفاء", null=True, blank=True)
    reply_notes = models.TextField("ملاحظات الرد", blank=True, default="")
    reply_marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="outgoing_reply_marked", verbose_name="سجّل الرد")

    @property
    def is_draft(self) -> bool:
        return self.sent_at is None

    @property
    def awaiting_reply(self) -> bool:
        return self.kind == self.Kind.REQUEST and self.sent_at is not None and self.reply_received_at is None

    class Meta:
        verbose_name = "مراسلة صادرة"
        verbose_name_plural = "المراسلات الصادرة"
        ordering = ["recorded_at", "id"]


class SubjectAction(models.Model):
    """إجراء سجّله الموظف على الموضوع (خيار + ملاحظات) ويظهر في ملخص الأحداث."""
    subject = models.ForeignKey("subjects.Subject", on_delete=models.CASCADE, related_name="actions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    choice = models.ForeignKey("core.ActionChoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    label = models.CharField(max_length=150)
    notes = models.TextField(blank=True)
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class SubjectActionFile(models.Model):
    """مرفق على إجراء تنفيذ؛ يُحفظ في الخزينة الآمنة ويظهر اسمه في ملخص الأحداث."""
    action = models.ForeignKey(SubjectAction, on_delete=models.CASCADE, related_name="files")
    original_filename = models.CharField(max_length=255)
    stored_relative_path = models.CharField(max_length=500)
    file_size = models.PositiveBigIntegerField(default=0)
    mime_type = models.CharField(max_length=120, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class StepSuspension(models.Model):
    """تعليق خطوة واحدة (صاحب العهدة) لاستيفاء مستند من شخص أو وحدة، دون إيقاف بقية الفروع."""
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="step_suspensions")
    recipient = models.ForeignKey("workflow.ReferralRecipient", on_delete=models.CASCADE, related_name="suspensions")
    holder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    required_item = models.CharField("المستند المطلوب", max_length=255)
    requested_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    requested_unit = models.ForeignKey("organization.OrgUnit", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    follow_up_date = models.DateField("تاريخ المتابعة", null=True, blank=True)
    prior_status = models.CharField(max_length=30)
    suspended_at = models.DateTimeField(auto_now_add=True)
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    lift_kind = models.CharField(max_length=10, blank=True)  # UPLOAD / CANCEL
    reminded = models.BooleanField(default=False)

    class Meta:
        ordering = ["-suspended_at"]

    @property
    def requested_label(self):
        if self.requested_user_id:
            return self.requested_user.get_full_name() or self.requested_user.username
        return str(self.requested_unit) if self.requested_unit_id else ""
