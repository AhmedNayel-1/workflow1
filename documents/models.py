"""
نموذج المستند المستقل عن الموضوع، وعلاقة Many-to-Many بينهما،
وإدارة النسخ المتعددة والمرفقات المخزنة في خزينة معزولة ببصمة SHA-256.
"""
from pathlib import Path
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models


class Document(models.Model):
    class SourceType(models.TextChoices):
        INCOMING = "INCOMING", "وارد"
        OUTGOING = "OUTGOING", "صادر"
        INTERNAL = "INTERNAL", "مستند داخلي"

    class DocStatus(models.TextChoices):
        DRAFT = "DRAFT", "مسودة"
        REGISTERED = "REGISTERED", "مسجل"
        APPROVED = "APPROVED", "معتمد"
        ARCHIVED = "ARCHIVED", "مؤرشف"

    internal_number = models.CharField("الرقم الداخلي للمستند", max_length=40, unique=True, db_index=True)
    external_in_out_number = models.CharField("رقم الصادر / الوارد الخارجي", max_length=80, blank=True)
    doc_type = models.ForeignKey("core.DocumentType", on_delete=models.PROTECT, verbose_name="نوع المستند")
    title = models.CharField("عنوان المستند", max_length=255)
    document_date = models.DateField("تاريخ المستند", null=True, blank=True)
    received_date = models.DateField("تاريخ الورود", null=True, blank=True)
    sender_entity = models.CharField("الجهة المرسلة", max_length=180, blank=True)
    receiver_entity = models.CharField("الجهة المستلمة", max_length=180, blank=True)
    confidentiality = models.ForeignKey(
        "core.ConfidentialityLevel",
        on_delete=models.PROTECT,
        verbose_name="درجة السرية",
    )
    summary = models.TextField("ملخص المحتوى", blank=True)
    source_type = models.CharField("مصدر المستند", max_length=20, choices=SourceType.choices, default=SourceType.INCOMING)
    status = models.CharField("حالة المستند", max_length=20, choices=DocStatus.choices, default=DocStatus.REGISTERED)
    current_version_number = models.PositiveIntegerField("رقم النسخة الحالية", default=1)
    subjects = models.ManyToManyField(
        "subjects.Subject",
        through="SubjectDocumentLink",
        related_name="documents",
        verbose_name="الموضوعات المرتبطة",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="منشئ السجل")
    created_at = models.DateTimeField("تاريخ التسجيل", auto_now_add=True)

    class Meta:
        verbose_name = "مستند"
        verbose_name_plural = "المستندات"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.internal_number} — {self.title}"


class SubjectDocumentLink(models.Model):
    """ربط Many-to-Many يوضح علاقة المستند بالموضوع الرئيسي والموضوعات المرتبطة."""
    class RelationType(models.TextChoices):
        PRIMARY = "PRIMARY", "مستند أساسي للموضوع"
        SUPPORTING = "SUPPORTING", "مستند داعم / مرفق"
        GENERAL_DECISION = "GENERAL_DECISION", "قرار إداري عام مرتبط"
        OUTPUT = "OUTPUT", "مخرج تنفيذي"

    subject = models.ForeignKey("subjects.Subject", on_delete=models.CASCADE, verbose_name="الموضوع")
    document = models.ForeignKey(Document, on_delete=models.CASCADE, verbose_name="المستند")
    is_primary_subject = models.BooleanField("موضوع رئيسي", default=False)
    relation_type = models.CharField("طبيعة العلاقة", max_length=30, choices=RelationType.choices, default=RelationType.SUPPORTING)
    linked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="ربط بواسطة")
    linked_at = models.DateTimeField("تاريخ الربط", auto_now_add=True)

    class Meta:
        verbose_name = "ربط مستند بموضوع"
        verbose_name_plural = "روابط المستندات بالموضوعات"
        unique_together = [("subject", "document")]


class DocumentVersion(models.Model):
    """إصدارات المستند غير القابلة للاستبدال (الاحتفاظ بالنسخ السابقة دائماً)."""
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name="المستند",
    )
    version_number = models.PositiveIntegerField("رقم النسخة")
    is_approved = models.BooleanField("نسخة معتمدة (False = مسودة)", default=False)
    status_label = models.CharField("حالة النسخة", max_length=40, default="مسودة")
    change_reason = models.CharField("سبب التعديل / الإصدار", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="منشئ النسخة")
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)

    class Meta:
        verbose_name = "نسخة مستند"
        verbose_name_plural = "نسخ المستندات"
        unique_together = [("document", "version_number")]
        ordering = ["-version_number"]

    def save(self, *args, **kwargs):
        if self.pk and DocumentVersion.objects.filter(pk=self.pk, is_approved=True).exists():
            raise PermissionDenied("لا يجوز تعديل أو استبدال نسخة معتمدة؛ يجب إنشاء نسخة جديدة بإجراء رسمي.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_approved:
            raise PermissionDenied("لا يجوز حذف نسخة مستند معتمدة.")
        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.document.internal_number} v{self.version_number}"


class Attachment(models.Model):
    """المرفقات المخزنة في خزينة معزولة ببصمة SHA-256."""
    document_version = models.ForeignKey(
        DocumentVersion,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="نسخة المستند",
    )
    original_filename = models.CharField("اسم الملف الأصلي", max_length=255)
    stored_relative_path = models.CharField("المسار المعزول", max_length=500)
    attachment_type = models.CharField("نوع المرفق", max_length=80, default="ملف رسمي")
    description = models.CharField("وصف المرفق", max_length=255, blank=True)
    mime_type = models.CharField("نوع المحتوى MIME", max_length=120, blank=True)
    file_size = models.PositiveBigIntegerField("حجم الملف (بايت)", default=0)
    sha256_hash = models.CharField("البصمة الرقمية SHA-256", max_length=64)
    is_approved = models.BooleanField("معتمد", default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="أضيف بواسطة")
    uploaded_at = models.DateTimeField("تاريخ الإضافة", auto_now_add=True)

    class Meta:
        verbose_name = "مرفق"
        verbose_name_plural = "المرفقات"
        ordering = ["-uploaded_at"]

    def save(self, *args, **kwargs):
        if self.document_version_id and DocumentVersion.objects.filter(
            pk=self.document_version_id, is_approved=True
        ).exists():
            raise PermissionDenied("لا يجوز تعديل أو إضافة مرفقات على نسخة معتمدة؛ أنشئ نسخة جديدة بإجراء رسمي.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.document_version_id and self.document_version.is_approved:
            raise PermissionDenied("لا يجوز حذف مرفق تابع لنسخة مستند معتمدة.")
        super().delete(*args, **kwargs)

    @property
    def file_extension(self) -> str:
        return Path(self.original_filename).suffix.lower()

    @property
    def preview_kind(self) -> str:
        ext = self.file_extension
        mime = (self.mime_type or "").lower()
        if ext == ".pdf" or mime == "application/pdf":
            return "pdf"
        if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"} or mime.startswith("image/"):
            return "image"
        if ext in {".mp3", ".wav", ".ogg", ".m4a"} or mime.startswith("audio/"):
            return "audio"
        if ext in {".mp4", ".webm", ".mov"} or mime.startswith("video/"):
            return "video"
        if ext in {".csv", ".tsv"} or mime in {"text/csv", "text/tab-separated-values"}:
            return "csv"
        if ext == ".json" or mime == "application/json":
            return "json"
        if ext in {".txt", ".md", ".log", ".xml", ".yml", ".yaml"} or mime == "text/plain":
            return "text"
        if ext in {".zip", ".rar", ".7z"}:
            return "archive"
        if ext in {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".rtf"}:
            return "office"
        return "other"

    def __str__(self):
        return f"{self.original_filename} (v{self.document_version.version_number})"
