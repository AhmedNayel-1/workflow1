"""
محرك الإجراءات ومسارات العمل المرنة:
- قوالب مسارات افتراضية بإصدارات مؤرخة (WorkflowTemplateVersion) قابلة للتغيير بحرية وفق الصلاحيات.
- محرك إحالات يدعم المباشرة، المتتابعة، المتوازية، والاطلاع "للعلم فقط".
- منع الإحالات المكررة عبر idempotency_key.
- إدارة المهام المستقلة عن الموضوع وعن الإحالة.
"""
from django.conf import settings
from django.db import models


class WorkflowTemplate(models.Model):
    """قالب المسار المقترح لنوع معاملة (مجرد اقتراح لتسهيل العمل وليس قيداً ثابتاً)."""
    code = models.CharField("كود القالب", max_length=50, unique=True)
    name = models.CharField("اسم المسار", max_length=180)
    transaction_type = models.ForeignKey(
        "core.TransactionType",
        on_delete=models.CASCADE,
        related_name="workflow_templates",
        verbose_name="نوع المعاملة",
    )
    sector = models.ForeignKey(
        "organization.Sector",
        on_delete=models.CASCADE,
        verbose_name="القطاع",
    )
    is_active = models.BooleanField("مفعل", default=True)

    class Meta:
        verbose_name = "قالب مسار عمل"
        verbose_name_plural = "قوالب مسارات العمل"

    def __str__(self):
        return self.name


class WorkflowTemplateVersion(models.Model):
    """إصدارات قوالب المسارات لضمان ثبات مسار المعاملات الجارية عند تحديث القالب."""
    template = models.ForeignKey(
        WorkflowTemplate,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="القالب",
    )
    version_number = models.PositiveIntegerField("رقم الإصدار", default=1)
    effective_from = models.DateField("تاريخ بدء العمل بالإصدار")
    is_active = models.BooleanField("الإصدار المعتمد حالياً", default=True)
    notes = models.TextField("ملاحظات الإصدار", blank=True)

    class Meta:
        verbose_name = "إصدار قالب مسار"
        verbose_name_plural = "إصدارات قوالب المسارات"
        unique_together = [("template", "version_number")]
        ordering = ["-version_number"]

    def __str__(self):
        return f"{self.template.name} — v{self.version_number}"


class WorkflowStepDefinition(models.Model):
    """خطوات مقترحة داخل إصدار القالب."""
    template_version = models.ForeignKey(
        WorkflowTemplateVersion,
        on_delete=models.CASCADE,
        related_name="steps",
        verbose_name="إصدار القالب",
    )
    step_order = models.PositiveSmallIntegerField("ترتيب الخطوة")
    step_title = models.CharField("عنوان الخطوة", max_length=180)
    suggested_unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="الوحدة المقترحة",
    )
    suggested_action = models.CharField("الإجراء المقترح", max_length=150, blank=True)
    sla_hours = models.PositiveIntegerField("مهلة التنفيذ (ساعة)", null=True, blank=True)
    is_optional = models.BooleanField("خطوة اختيارية يمكن تجاوزها", default=True)

    class Meta:
        verbose_name = "خطوة مسار مقترحة"
        verbose_name_plural = "خطوات المسارات المقترحة"
        ordering = ["step_order"]


class Referral(models.Model):
    """إحالة موضوع (مباشرة / متتابعة / متوازية / للعلم فقط)."""
    class RoutingMode(models.TextChoices):
        DIRECT = "DIRECT", "إحالة مباشرة"
        SEQUENTIAL = "SEQUENTIAL", "إحالة متتابعة"
        PARALLEL = "PARALLEL", "إحالة متوازية"

    class Purpose(models.TextChoices):
        FOR_INFO = "FOR_INFO", "للعلم / للاطلاع (دون تكليف)"
        FOR_STUDY = "FOR_STUDY", "للدراسة وإبداء الرأي"
        FOR_EXECUTION = "FOR_EXECUTION", "للتنفيذ"
        FOR_MEMO = "FOR_MEMO", "لإعداد مذكرة"
        FOR_APPROVAL = "FOR_APPROVAL", "للاعتماد"

    class ParallelCompletionRule(models.TextChoices):
        ALL = "ALL", "انتظار جميع الردود"
        SPECIFIC_UNIT = "SPECIFIC_UNIT", "انتظار رد جهة محددة"
        FIRST_RESPONSE = "FIRST_RESPONSE", "استكمال بمجرد ورود أول رد"
        ALLOW_WITH_MISSING = "ALLOW_WITH_MISSING", "السماح بالاستكمال مع تسجيل الجهات التي لم ترد"

    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.CASCADE,
        related_name="referrals",
        verbose_name="الموضوع",
    )
    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_referrals",
        verbose_name="المُحيل",
    )
    acting_on_behalf_of = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="delegated_referrals",
        verbose_name="بالنيابة عن",
    )
    coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="coordinated_referrals",
        verbose_name="منسق الإحالة المتوازية",
    )
    routing_mode = models.CharField("نمط الإحالة", max_length=20, choices=RoutingMode.choices, default=RoutingMode.DIRECT)
    purpose = models.CharField("غرض الإحالة", max_length=20, choices=Purpose.choices, default=Purpose.FOR_EXECUTION)
    parallel_completion_rule = models.CharField(
        "شرط استكمال الإحالة المتوازية",
        max_length=30,
        choices=ParallelCompletionRule.choices,
        default=ParallelCompletionRule.ALL,
    )
    required_unit_for_completion = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mandatory_completion_referrals",
        verbose_name="الجهة المطلوب ردها تحديداً",
    )
    confidentiality = models.ForeignKey(
        "core.ConfidentialityLevel",
        on_delete=models.PROTECT,
        verbose_name="درجة سرية الإحالة",
    )
    priority = models.ForeignKey(
        "core.PriorityLevel",
        on_delete=models.PROTECT,
        verbose_name="الأولوية",
    )
    notes = models.TextField("التوجيه والملاحظات", blank=True)
    due_date = models.DateField("الموعد المطلوب", null=True, blank=True)
    is_completed = models.BooleanField("مكتملة", default=False)
    is_withdrawn = models.BooleanField("مسحوبة", default=False)
    completed_at = models.DateTimeField("تاريخ الاكتمال", null=True, blank=True)
    last_reminded_at = models.DateTimeField("آخر تذكير قبل الاستحقاق", null=True, blank=True)
    escalated_at = models.DateTimeField("تاريخ التصعيد التلقائي", null=True, blank=True)
    idempotency_key = models.CharField(
        "مفتاح منع التكرار",
        max_length=80,
        unique=True,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("تاريخ الإحالة", auto_now_add=True)

    class Meta:
        verbose_name = "إحالة"
        verbose_name_plural = "الإحالات"
        ordering = ["-created_at"]

    @property
    def is_for_info_only(self) -> bool:
        return self.purpose == self.Purpose.FOR_INFO


class ReferralRecipient(models.Model):
    """المحال إليهم ضمن الإحالة (يدعم مستخدمين ووحدات وترتيب متتابع)."""
    class RecipientStatus(models.TextChoices):
        WAITING_TURN = "WAITING_TURN", "في انتظار الدور (متتابع)"
        PENDING = "PENDING", "بانتظار الاستلام"
        RECEIVED = "RECEIVED", "تم الاستلام"
        VIEWED_ONLY = "VIEWED_ONLY", "تم الاطلاع (للعلم)"
        RESPONDED = "RESPONDED", "تم الرد / التنفيذ"
        SKIPPED_NO_RESPONSE = "SKIPPED_NO_RESPONSE", "استُكملت دون رد"
        RETURNED = "RETURNED", "مرفوضة / مُرجعة"
        WITHDRAWN = "WITHDRAWN", "مسحوبة من المحيل"

    referral = models.ForeignKey(
        Referral,
        on_delete=models.CASCADE,
        related_name="recipients",
        verbose_name="الإحالة",
    )
    sequence_order = models.PositiveSmallIntegerField("الترتيب", default=1)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="incoming_referral_items",
        verbose_name="المستخدم المحال إليه",
    )
    target_unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="unit_referral_items",
        verbose_name="الوحدة المحال إليها",
    )
    is_active_step = models.BooleanField("الخطوة النشطة حالياً", default=True)
    status = models.CharField("حالة الاستلام والتنفيذ", max_length=25, choices=RecipientStatus.choices, default=RecipientStatus.PENDING)
    received_at = models.DateTimeField("تاريخ الاستلام", null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actually_received_referrals",
        verbose_name="المستلم الفعلي",
    )
    response_notes = models.TextField("الرد / الإفادة", blank=True)
    responded_at = models.DateTimeField("تاريخ الرد", null=True, blank=True)

    class Meta:
        verbose_name = "مستلم إحالة"
        verbose_name_plural = "مستلمو الإحالات"
        ordering = ["sequence_order", "id"]
        indexes = [
            models.Index(fields=["target_user", "status", "is_active_step"]),
            models.Index(fields=["target_unit", "status", "is_active_step"]),
        ]


class Task(models.Model):
    """المهام والتكليفات التنفيذية (منفصلة عن الموضوع وعن الإحالة)."""
    class TaskStatus(models.TextChoices):
        NEW = "NEW", "جديدة"
        RECEIVED = "RECEIVED", "مستلمة"
        IN_PROGRESS = "IN_PROGRESS", "قيد التنفيذ"
        PAUSED = "PAUSED", "متوقفة"
        WAITING_EXTERNAL = "WAITING_EXTERNAL", "في انتظار جهة أخرى"
        COMPLETED = "COMPLETED", "مكتملة"
        REJECTED = "REJECTED", "مرفوضة"
        CANCELLED = "CANCELLED", "ملغاة"

    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name="الموضوع",
    )
    referral = models.ForeignKey(
        Referral,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_tasks",
        verbose_name="الإحالة المولِّدة",
    )
    title = models.CharField("عنوان المهمة", max_length=200)
    description = models.TextField("وصف المهمة", blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_tasks",
        verbose_name="الموظف المكلف",
    )
    assigned_unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="الجهة التابع لها",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="delegated_tasks",
        verbose_name="المكلِّف",
    )
    priority = models.ForeignKey("core.PriorityLevel", on_delete=models.PROTECT, verbose_name="الأولوية")
    status = models.CharField("حالة المهمة", max_length=25, choices=TaskStatus.choices, default=TaskStatus.NEW)
    assigned_at = models.DateTimeField("تاريخ التكليف", auto_now_add=True)
    due_date = models.DateField("الموعد النهائي", null=True, blank=True)
    last_reminded_at = models.DateTimeField("آخر تذكير قبل الاستحقاق", null=True, blank=True)
    escalated_at = models.DateTimeField("تاريخ التصعيد التلقائي", null=True, blank=True)
    outcome = models.TextField("النتيجة / الملاحظات", blank=True)
    completed_at = models.DateTimeField("تاريخ الإنجاز", null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_tasks",
        verbose_name="أُنجزت بواسطة",
    )

    class Meta:
        verbose_name = "مهمة"
        verbose_name_plural = "المهام والتكليفات"
        ordering = ["-assigned_at"]
        indexes = [
            models.Index(fields=["assigned_to", "status", "due_date"]),
            models.Index(fields=["subject", "status"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
