from django.conf import settings
from django.db import models


class ChatConversation(models.Model):
    """محادثة ثنائية (Direct) أو جماعية (Group) معزولة لأعضائها فقط."""

    class ConversationType(models.TextChoices):
        DIRECT = "direct", "محادثة فردية"
        GROUP = "group", "مجموعة محادثة"

    type = models.CharField("النوع", max_length=20, choices=ConversationType.choices, default=ConversationType.DIRECT)
    name = models.CharField("اسم المجموعة", max_length=180, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_chat_conversations",
        verbose_name="أنشئت بواسطة",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="chat_conversations",
        verbose_name="الأعضاء",
    )
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)

    class Meta:
        verbose_name = "محادثة فورية"
        verbose_name_plural = "المحادثات الفورية"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.name or f"محادثة #{self.id}"


class ChatMessage(models.Model):
    """رسالة فورية داخل المحادثة مع دعم إرفاق الملفات الآمن عبر الخزينة."""

    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="المحادثة",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_chat_messages",
        verbose_name="المرسل",
    )
    text = models.TextField("نص الرسالة", blank=True)
    attachment_name = models.CharField("اسم الملف المرفق", max_length=255, blank=True)
    attachment_stored_path = models.CharField("مسار الخزينة", max_length=500, blank=True)
    attachment_size = models.PositiveBigIntegerField("حجم المرفق", default=0)
    attachment_mime = models.CharField("نوع MIME", max_length=120, blank=True)
    attachment_sha256 = models.CharField("بصمة SHA-256", max_length=64, blank=True)
    read_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="read_chat_messages",
        blank=True,
        verbose_name="قُرئت بواسطة",
    )
    created_at = models.DateTimeField("تاريخ الإرسال", auto_now_add=True)

    class Meta:
        verbose_name = "رسالة محادثة"
        verbose_name_plural = "رسائل المحادثات"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.sender}: {self.text[:40] or self.attachment_name}"

    @property
    def preview_kind(self) -> str:
        name = (self.attachment_name or "").lower()
        mime = (self.attachment_mime or "").lower()
        if name.endswith(".pdf") or mime == "application/pdf":
            return "pdf"
        if mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")):
            return "image"
        if mime.startswith("audio/") or name.endswith((".mp3", ".wav", ".ogg", ".m4a")):
            return "audio"
        if mime.startswith("video/") or name.endswith((".mp4", ".webm", ".mov")):
            return "video"
        if name.endswith((".csv", ".tsv")) or mime in {"text/csv", "text/tab-separated-values"}:
            return "csv"
        if name.endswith(".json") or mime == "application/json":
            return "json"
        if mime.startswith("text/") or name.endswith((".txt", ".md", ".log", ".xml", ".yml", ".yaml", ".rtf")):
            return "text"
        if name.endswith((".zip", ".rar", ".7z")):
            return "archive"
        if name.endswith((".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")):
            return "office"
        return "other"
