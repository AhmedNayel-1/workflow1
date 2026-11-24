from django.conf import settings
from django.db import models


class Committee(models.Model):
    """اللجان المؤسسية (شئون العاملين، العليا للتدريب، الإسكان...)."""
    code = models.CharField("كود اللجنة", max_length=40, unique=True)
    name = models.CharField("اسم اللجنة", max_length=180)
    sector = models.ForeignKey(
        "organization.Sector",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="القطاع المختص",
    )
    chair = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="chaired_committees",
        verbose_name="رئيس اللجنة",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="committee_memberships",
        blank=True,
        verbose_name="أعضاء اللجنة",
    )
    mandate = models.TextField("الاختصاص والتشكيل", blank=True)
    is_active = models.BooleanField("مفعلة", default=True)

    class Meta:
        verbose_name = "لجنة"
        verbose_name_plural = "اللجان"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CommitteeMeeting(models.Model):
    """اجتماع لجنة ومحضر الاجتماع."""
    class MeetingStatus(models.TextChoices):
        SCHEDULED = "SCHEDULED", "مجدول"
        CONVENED = "CONVENED", "منعقد"
        APPROVED = "APPROVED", "معتمد المحضر"

    committee = models.ForeignKey(Committee, on_delete=models.CASCADE, related_name="meetings", verbose_name="اللجنة")
    meeting_number = models.CharField("رقم الجلسة", max_length=40)
    meeting_date = models.DateField("تاريخ الاجتماع")
    location = models.CharField("مكان الانعقاد", max_length=150, blank=True)
    minutes_summary = models.TextField("ملخص محضر الاجتماع", blank=True)
    status = models.CharField("حالة المحضر", max_length=20, choices=MeetingStatus.choices, default=MeetingStatus.SCHEDULED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="أعد المحضر")
    created_at = models.DateTimeField("تاريخ التسجيل", auto_now_add=True)

    class Meta:
        verbose_name = "اجتماع لجنة"
        verbose_name_plural = "اجتماعات اللجان"
        ordering = ["-meeting_date", "-id"]

    def __str__(self):
        return f"{self.committee.name} — جلسة {self.meeting_number}"


class CommitteeAgendaItem(models.Model):
    """عرض موضوع على اللجنة وتسجيل التوصية والنتيجة."""
    class ResolutionType(models.TextChoices):
        PENDING = "PENDING", "معروض للبحث"
        APPROVED = "APPROVED", "موافقة"
        REJECTED = "REJECTED", "رفض"
        DEFERRED = "DEFERRED", "تأجيل للاستيفاء"

    meeting = models.ForeignKey(CommitteeMeeting, on_delete=models.CASCADE, related_name="agenda_items", verbose_name="الاجتماع")
    subject = models.ForeignKey(
        "subjects.Subject",
        on_delete=models.CASCADE,
        related_name="committee_items",
        verbose_name="الموضوع",
    )
    memo = models.ForeignKey(
        "subjects.Memo",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="مذكرة العرض",
    )
    recommendation = models.TextField("التوصية", blank=True)
    resolution_type = models.CharField("نتيجة العرض", max_length=20, choices=ResolutionType.choices, default=ResolutionType.PENDING)
    resolution_text = models.TextField("نص قرار اللجنة", blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="مسجل النتيجة")
    recorded_at = models.DateTimeField("تاريخ التسجيل", auto_now_add=True)

    class Meta:
        verbose_name = "بند جدول أعمال لجنة"
        verbose_name_plural = "بنود جداول أعمال اللجان"
        ordering = ["id"]
