"""
السجل التاريخي التشغيلي غير القابل للتعديل أو الحذف (ActivityLog)
وسجل التدقيق الأمني المنفصل منطقياً للعمليات الحساسة (AuditLog).
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models


class ActivityLog(models.Model):
    """سجل الحركة التاريخي المركزي لكل موضوع (Append-Only)."""
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.PROTECT,
        related_name="activity_logs",
        verbose_name="الموضوع",
    )
    action_type = models.CharField("نوع الإجراء", max_length=60)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="performed_activities",
        verbose_name="المستخدم الفعلي المنفذ",
    )
    acting_on_behalf_of = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="delegated_activities",
        verbose_name="صاحب الصفة / المسؤول المفوِّض",
    )
    delegation = models.ForeignKey(
        "accounts.Delegation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="مرجع التفويض",
    )
    description = models.TextField("وصف الإجراء")
    metadata_json = models.JSONField("بيانات تفصيلية", default=dict, blank=True)
    correction_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="corrections",
        verbose_name="تصحيح للإجراء رقم",
    )
    correction_reason = models.CharField("سبب التصحيح", max_length=255, blank=True)
    created_at = models.DateTimeField("تاريخ ووقت الإجراء", auto_now_add=True)

    class Meta:
        verbose_name = "سجل حركة موضوع"
        verbose_name_plural = "سجل الحركة التاريخي"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["subject", "created_at"]),
            models.Index(fields=["actor_user", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("لا يجوز تعديل سجل الحركة التاريخي؛ أضف إجراءً تصحيحياً جديداً.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("لا يجوز حذف سجل الحركة التاريخي.")

    def __str__(self):
        return f"[{self.subject.internal_number}] {self.action_type} - {self.actor_user}"


class AuditLog(models.Model):
    """سجل التدقيق الأمني المنفصل للعمليات الحساسة (Append-Only)."""
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="المستخدم",
    )
    action = models.CharField("العملية", max_length=80)
    model_name = models.CharField("الكيان المتأثر", max_length=80)
    object_id = models.CharField("معرّف الكيان", max_length=64, blank=True)
    before_state = models.JSONField("القيم السابقة", default=dict, blank=True)
    after_state = models.JSONField("القيم اللاحقة", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("عنوان الاتصال", null=True, blank=True)
    outcome = models.CharField("النتيجة", max_length=30, default="SUCCESS")
    reason = models.TextField("السبب", blank=True)
    created_at = models.DateTimeField("وقت التنفيذ", auto_now_add=True)

    class Meta:
        verbose_name = "سجل تدقيق أمني"
        verbose_name_plural = "سجلات التدقيق الأمني"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["actor_user", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("سجل التدقيق الأمني غير قابل للتعديل.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("سجل التدقيق الأمني غير قابل للحذف.")
