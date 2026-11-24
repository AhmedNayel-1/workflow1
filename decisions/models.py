"""
نموذج القرارات الإدارية:
يميز بوضوح بين:
1. الإعداد (DRAFT)
2. المراجعة (UNDER_REVIEW)
3. الاعتماد (APPROVED)
4. الإصدار (ISSUED)
5. التوزيع (DISTRIBUTING)
6. التنفيذ عبر مهام تنفيذية منفصلة لكل جهة (EXECUTING)
7. إغلاق إجراءات التنفيذ (COMPLETED)
"""
from django.conf import settings
from django.db import models


class Decision(models.Model):
    class DecisionType(models.TextChoices):
        TRANSFER = "TRANSFER", "قرار نقل"
        PENALTY = "PENALTY", "قرار جزاء"
        ALLOWANCE = "ALLOWANCE", "قرار علاوة تشجيعية"
        HOUSING = "HOUSING", "قرار إسكان مصلحي"
        GENERAL = "GENERAL", "قرار إداري عام"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "قيد الإعداد (مسودة)"
        UNDER_REVIEW = "UNDER_REVIEW", "قيد المراجعة"
        APPROVED = "APPROVED", "معتمد"
        ISSUED = "ISSUED", "صادر"
        DISTRIBUTING = "DISTRIBUTING", "قيد التوزيع"
        EXECUTING = "EXECUTING", "قيد التنفيذ"
        COMPLETED = "COMPLETED", "مكتمل التنفيذ"
        CANCELLED = "CANCELLED", "ملغى"

    decision_number = models.CharField("رقم القرار", max_length=40, unique=True, db_index=True)
    decision_type = models.CharField("نوع القرار", max_length=30, choices=DecisionType.choices, default=DecisionType.GENERAL)
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="decisions",
        verbose_name="الموضوع المرتبط",
    )
    committee_item = models.ForeignKey(
        "committees.CommitteeAgendaItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="بند اللجنة المرجعي",
    )
    title = models.CharField("عنوان القرار", max_length=255)
    body = models.TextField("نص ومواد القرار")
    issuing_authority = models.CharField("جهة الإصدار", max_length=180)
    approving_authority = models.CharField("جهة الاعتماد", max_length=180)
    status = models.CharField("حالة القرار", max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="drafted_decisions",
        verbose_name="أعد المشروع",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_decisions",
        verbose_name="اعتمده",
    )
    approved_at = models.DateTimeField("تاريخ الاعتماد", null=True, blank=True)
    issued_date = models.DateField("تاريخ الإصدار", null=True, blank=True)
    idempotency_key = models.CharField("مفتاح منع التكرار", max_length=80, unique=True, null=True, blank=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)

    class Meta:
        verbose_name = "قرار إداري"
        verbose_name_plural = "القرارات الإدارية"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.decision_number} — {self.title}"


class DecisionDistribution(models.Model):
    """الجهات المطلوب إخطارها بالقرار."""
    decision = models.ForeignKey(Decision, on_delete=models.CASCADE, related_name="distributions")
    target_unit = models.ForeignKey("organization.OrgUnit", on_delete=models.PROTECT, verbose_name="الجهة المخطرة")
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="المستلم",
    )
    sent_at = models.DateTimeField("تاريخ الإرسال", auto_now_add=True)
    acknowledged_at = models.DateTimeField("تاريخ الاستلام", null=True, blank=True)

    class Meta:
        verbose_name = "توزيع قرار"
        verbose_name_plural = "توزيعات القرارات"


class DecisionExecutionItem(models.Model):
    """مهام تنفيذ القرار المنفصلة لكل جهة مكلفة بالتنفيذ."""
    class ExecutionStatus(models.TextChoices):
        PENDING = "PENDING", "بانتظار التنفيذ"
        IN_PROGRESS = "IN_PROGRESS", "قيد التنفيذ"
        COMPLETED = "COMPLETED", "تم التنفيذ"
        DELAYED = "DELAYED", "متأخر"

    decision = models.ForeignKey(Decision, on_delete=models.CASCADE, related_name="execution_items")
    assigned_unit = models.ForeignKey("organization.OrgUnit", on_delete=models.PROTECT, verbose_name="الجهة المكلفة بالتنفيذ")
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name="الموظف المسؤول",
    )
    required_action = models.CharField("المطلوب تنفيذه", max_length=255)
    assigned_at = models.DateTimeField("تاريخ التكليف", auto_now_add=True)
    due_date = models.DateField("الموعد النهائي", null=True, blank=True)
    execution_status = models.CharField("حالة التنفيذ", max_length=20, choices=ExecutionStatus.choices, default=ExecutionStatus.PENDING)
    execution_result = models.TextField("نتيجة التنفيذ", blank=True)
    proof_document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="المستند الدال على التنفيذ",
    )
    completed_at = models.DateTimeField("تاريخ إتمام التنفيذ", null=True, blank=True)

    class Meta:
        verbose_name = "بند تنفيذ قرار"
        verbose_name_plural = "بنود تنفيذ القرارات"
        ordering = ["id"]
