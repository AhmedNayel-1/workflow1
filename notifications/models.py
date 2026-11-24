from django.conf import settings
from django.db import models


class Notification(models.Model):
    """التنبيهات الداخلية المضبوطة مع مراعاة عدم كشف تفاصيل السري للغاية."""
    class Category(models.TextChoices):
        REFERRAL = "REFERRAL", "إحالة جديدة"
        INCOMING_REFERRAL = "INCOMING_REFERRAL", "إحالة واردة"
        REPLY_MEMO = "REPLY_MEMO", "رد ومذكرة"
        DECISION_TASK = "DECISION_TASK", "مهمة / قرار"
        APPROVAL_NEEDED = "APPROVAL_NEEDED", "بانتظار الاعتماد"
        ESCALATION_OVERDUE = "ESCALATION_OVERDUE", "تصعيد تأخير"
        FULFILLMENT = "FULFILLMENT", "استيفاء تعليق"
        TASK = "TASK", "مهمة / تكليف"
        DEADLINE = "DEADLINE", "موعد استحقاق"
        SUSPENSION = "SUSPENSION", "تعليق / استيفاء"
        DECISION = "DECISION", "قرار إداري"
        SYSTEM = "SYSTEM", "تنبيه نظام"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="المستلم",
    )
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="الموضوع المرتبط",
    )
    category = models.CharField("الفئة", max_length=30, choices=Category.choices, default=Category.SYSTEM)
    priority = models.CharField("الأولوية", max_length=20, default="NORMAL")
    target_level = models.CharField("المستوى المستهدف", max_length=10, default="L5", blank=True)
    reason_for_level = models.CharField("سبب التخصيص للمستوى", max_length=200, blank=True)
    title = models.CharField("العنوان", max_length=200)
    message = models.TextField("الرسالة")
    link_url = models.CharField("الرابط", max_length=255, blank=True)
    is_read = models.BooleanField("مقروء", default=False)
    created_at = models.DateTimeField("تاريخ التنبيه", auto_now_add=True)

    class Meta:
        verbose_name = "تنبيه"
        verbose_name_plural = "التنبيهات"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "created_at"]),
        ]

    def __str__(self):
        return f"{self.recipient.username}: {self.title}"
