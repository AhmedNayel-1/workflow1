"""
البيانات المرجعية والترقيم المتزامن الآمن وسجل الأخطاء التقنية.
"""
from django.db import models, transaction
from django.utils import timezone


class ConfidentialityLevel(models.Model):
    """درجات السرية (عادي، سري، سري للغاية، قابلة للتوسع)."""
    code = models.CharField("الكود", max_length=30, unique=True)
    name = models.CharField("المسمى", max_length=100)
    rank = models.PositiveSmallIntegerField(
        "المستوى الرقمي",
        default=1,
        help_text="1=عادي، 2=سري، 3=سري للغاية",
    )
    overrides_hierarchy = models.BooleanField(
        "يمنع الاطلاع الهرمي تلقائياً",
        default=False,
        help_text="إذا فُعّل، يُمنع الاطلاع الهرمي ويُشترط تصريح صريح أو إحالة مباشرة.",
    )
    is_active = models.BooleanField("مفعل", default=True)

    class Meta:
        verbose_name = "درجة سرية"
        verbose_name_plural = "درجات السرية"
        ordering = ["rank", "id"]

    def __str__(self):
        return self.name


class PriorityLevel(models.Model):
    """درجات الأولوية القابلة للتعديل من واجهة الإدارة."""
    code = models.CharField("الكود", max_length=30, unique=True)
    name = models.CharField("المسمى", max_length=100)
    rank = models.PositiveSmallIntegerField("الترتيب", default=1)
    sla_days = models.PositiveSmallIntegerField("مهلة الإنجاز الافتراضية (أيام)", default=7)
    is_active = models.BooleanField("مفعل", default=True)

    class Meta:
        verbose_name = "درجة أولوية"
        verbose_name_plural = "درجات الأولوية"
        ordering = ["rank"]

    def __str__(self):
        return self.name


class TransactionType(models.Model):
    """أنواع المعاملات والموضوعات (نقل، جزاء، علاوة، إسكان، بيان عاجل...)."""
    code = models.CharField("الكود", max_length=50, unique=True)
    name = models.CharField("نوع المعاملة", max_length=150)
    sector = models.ForeignKey(
        "organization.Sector",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="القطاع المختص",
    )
    requires_committee = models.BooleanField("يتطلب عرض على لجنة", default=False)
    requires_decision = models.BooleanField("يتطلب قراراً إدارياً للإغلاق", default=False)
    requires_execution_proof = models.BooleanField("يتطلب إثبات تنفيذ للإغلاق", default=False)
    is_active = models.BooleanField("مفعل", default=True)

    class Meta:
        verbose_name = "نوع معاملة"
        verbose_name_plural = "أنواع المعاملات"
        ordering = ["name"]

    def __str__(self):
        return self.name


class DocumentType(models.Model):
    """أنواع المستندات المرجعية."""
    code = models.CharField("الكود", max_length=50, unique=True)
    name = models.CharField("نوع المستند", max_length=150)
    is_active = models.BooleanField("مفعل", default=True)

    class Meta:
        verbose_name = "نوع مستند"
        verbose_name_plural = "أنواع المستندات"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SuspensionReason(models.Model):
    """أسباب التعليق المرجعية القابلة للتحديث مع حفظ القيم القديمة تاريخياً."""
    code = models.CharField("الكود", max_length=50, unique=True)
    name = models.CharField("سبب التعليق", max_length=200)
    is_active = models.BooleanField("مفعل", default=True)

    class Meta:
        verbose_name = "سبب تعليق"
        verbose_name_plural = "أسباب التعليق"
        ordering = ["name"]

    def __str__(self):
        return self.name


class RetentionPolicy(models.Model):
    """سياسة الاحتفاظ بالمستندات والسجلات وفق لوائح الشركة."""
    code = models.CharField("الكود", max_length=50, unique=True)
    name = models.CharField("اسم السياسة", max_length=150)
    retention_years = models.PositiveSmallIntegerField("مدة الاحتفاظ (سنوات)", default=10)
    allow_auto_disposal = models.BooleanField(
        "يسمح بالإتلاف الآلي",
        default=False,
        help_text="افتراضياً False لمنع الحذف الآلي دون اعتماد رسمي.",
    )
    description = models.TextField("الضوابط والوصف", blank=True)
    is_active = models.BooleanField("مفعل", default=True)

    class Meta:
        verbose_name = "سياسة احتفاظ"
        verbose_name_plural = "سياسات الاحتفاظ"

    def __str__(self):
        return f"{self.name} ({self.retention_years} سنة)"


class SystemSequence(models.Model):
    """
    جدول الترقيم التسلسلي الآمن ضد التزامن (Concurrency-Safe Numbering).
    يستخدم select_for_update داخل معاملة قاعدة بيانات لمنع تكرار الأرقام عند التزاحم.
    """
    key = models.CharField("مفتاح الترقيم", max_length=50)
    year = models.PositiveIntegerField("السنة")
    prefix = models.CharField("البادئة", max_length=20)
    last_number = models.PositiveIntegerField("آخر رقم", default=0)

    class Meta:
        verbose_name = "تسلسل رقمي"
        verbose_name_plural = "التسلسلات الرقمية"
        unique_together = [("key", "year")]

    @classmethod
    def next_number(cls, key: str, prefix: str) -> str:
        current_year = timezone.now().year
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(
                key=key,
                year=current_year,
                defaults={"prefix": prefix, "last_number": 0},
            )
            seq.last_number += 1
            seq.save(update_fields=["last_number"])
            return f"{seq.prefix}-{current_year}-{seq.last_number:05d}"


class SystemErrorLog(models.Model):
    """
    سجل الأخطاء التقنية والعمليات غير المكتملة (مثل فشل إشعار أو تكامل)
    بحيث لا يؤدي فشل الإشعار إلى إلغاء إحالة أو قرار صحيح.
    """
    component = models.CharField("المكون", max_length=100)
    operation = models.CharField("العملية", max_length=150)
    error_message = models.TextField("تفاصيل الخطأ")
    reference_type = models.CharField("نوع الكيان", max_length=80, blank=True)
    reference_id = models.CharField("معرّف الكيان", max_length=80, blank=True)
    is_resolved = models.BooleanField("تمت المعالجة", default=False)
    created_at = models.DateTimeField("وقت الحدوث", auto_now_add=True)

    class Meta:
        verbose_name = "سجل أخطاء تقنية"
        verbose_name_plural = "سجل الأخطاء التقنية"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.component}: {self.operation} ({self.created_at:%Y-%m-%d %H:%M})"


class MemoTypeRef(models.Model):
    """أنواع المذكرات الرسمية القابلة للإضافة والتعديل والحذف من الإعدادات."""
    code = models.CharField("الكود", max_length=60, unique=True)
    name = models.CharField("نوع المذكرة", max_length=150)
    is_active = models.BooleanField("مفعل", default=True)

    class Meta:
        verbose_name = "نوع مذكرة مرجعي"
        verbose_name_plural = "أنواع المذكرات المرجعية"
        ordering = ["id"]

    def __str__(self):
        return self.name


class MemoRecipientRef(models.Model):
    """الجهات / المسؤولون الموجه إليهم المذكرات (قابل للتعديل من الإعدادات)."""
    code = models.CharField("الكود", max_length=60, unique=True)
    name = models.CharField("الجهة / المسؤول", max_length=180)
    is_active = models.BooleanField("مفعل", default=True)

    class Meta:
        verbose_name = "جهة موجه إليها مذكرة"
        verbose_name_plural = "الجهات الموجه إليها المذكرات"
        ordering = ["id"]

    def __str__(self):
        return self.name

