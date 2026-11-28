"""
إدارة المستخدمين، الأدوار، الصلاحيات متعددة الأبعاد، السكرتارية، والإنابة المؤقتة.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """حساب المستخدم المستقل المرتبط اختيارياً بسجل موظف ووحدة تنظيمية."""
    employee = models.OneToOneField(
        "organization.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_account",
        verbose_name="الموظف المرتبط",
    )
    job_display_title = models.CharField("الاسم الوظيفي الظاهر", max_length=150, blank=True)
    is_secretariat = models.BooleanField("حساب سكرتارية", default=False)
    is_system_admin = models.BooleanField("مسؤول نظام", default=False)
    activated_at = models.DateTimeField("تاريخ التفعيل", default=timezone.now)
    deactivated_at = models.DateTimeField("تاريخ الإيقاف", null=True, blank=True)

    class Meta:
        verbose_name = "مستخدم"
        verbose_name_plural = "المستخدمون"

    def __str__(self):
        name = self.get_full_name() or self.username
        if self.job_display_title:
            return f"{name} — {self.job_display_title}"
        return name

    @property
    def current_unit(self):
        return self.employee.current_unit if self.employee else None

    @property
    def current_sector(self):
        unit = self.current_unit
        return unit.sector if unit else None


class PermissionCode(models.Model):
    """رموز الصلاحيات الدقيقة داخل المنظومة."""
    code = models.CharField("كود الصلاحية", max_length=80, unique=True)
    name = models.CharField("الوصف", max_length=180)
    category = models.CharField("التصنيف", max_length=80, default="عام")

    class Meta:
        verbose_name = "رمز صلاحية"
        verbose_name_plural = "رموز الصلاحيات"
        ordering = ["category", "code"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Role(models.Model):
    """الدور الوظيفي في مصفوفة الصلاحيات (لا يعتمد على groups التقليدية فقط)."""
    code = models.CharField("كود الدور", max_length=50, unique=True)
    name = models.CharField("اسم الدور", max_length=150)
    description = models.TextField("الوصف", blank=True)
    allow_hierarchical_view = models.BooleanField(
        "يسمح بالاطلاع الهرمي على الموضوعات العادية للوحدات التابعة",
        default=False,
    )
    can_view_confidential = models.BooleanField(
        "صلاحية مستقلة للاطلاع على درجة سري",
        default=False,
    )
    can_view_top_secret = models.BooleanField(
        "صلاحية مستقلة للاطلاع على درجة سري للغاية (عند التكليف/التصريح)",
        default=False,
    )
    can_download_secret_attachments = models.BooleanField(
        "صلاحية تنزيل وطباعة مرفقات السري للغاية",
        default=False,
    )
    permissions = models.ManyToManyField(
        PermissionCode,
        through="RolePermission",
        related_name="roles",
        verbose_name="الصلاحيات",
    )

    class Meta:
        verbose_name = "دور وظيفي"
        verbose_name_plural = "الأدوار الوظيفية"
        ordering = ["name"]

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    """ربط الدور بالصلاحيات مع تحديد نطاق القطاع أو نوع المعاملة أو درجة السرية."""
    role = models.ForeignKey(Role, on_delete=models.CASCADE, verbose_name="الدور")
    permission = models.ForeignKey(PermissionCode, on_delete=models.CASCADE, verbose_name="الصلاحية")
    max_confidentiality_rank = models.PositiveSmallIntegerField(
        "أقصى درجة سرية مسموحة",
        default=3,
    )

    class Meta:
        verbose_name = "صلاحية دور"
        verbose_name_plural = "صلاحيات الأدوار"
        unique_together = [("role", "permission")]


class UserRoleAssignment(models.Model):
    """إسناد دور لمستخدم ضمن نطاق قطاع أو وحدة تنظيمية أو نوع معاملة محدد."""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="role_assignments",
        verbose_name="المستخدم",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="user_assignments",
        verbose_name="الدور",
    )
    sector = models.ForeignKey(
        "organization.Sector",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="نطاق القطاع (فارغ = كل القطاعات المسموحة)",
    )
    org_unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="نطاق الوحدة التنظيمية",
    )
    transaction_type = models.ForeignKey(
        "core.TransactionType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="نطاق نوع المعاملة",
    )
    is_active = models.BooleanField("مفعل", default=True)
    assigned_at = models.DateTimeField("تاريخ الإسناد", auto_now_add=True)

    class Meta:
        verbose_name = "تعيين دور مستخدم"
        verbose_name_plural = "تعيينات أدوار المستخدمين"

    def __str__(self):
        return f"{self.user.username} -> {self.role.name}"


class Delegation(models.Model):
    """
    إدارة السكرتارية والإنابة المؤقتة.
    لا تُمنح السكرتارية صلاحيات المسؤول تلقائياً، بل وفق هذا التفويض المحدد زمنياً وبإجراءات محددة.
    """
    class DelegationType(models.TextChoices):
        SECRETARIAT = "SECRETARIAT", "تفويض سكرتارية"
        ACTING = "ACTING", "إنابة مسؤول"

    delegator = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="delegations_granted",
        verbose_name="المسؤول المفوِّض",
    )
    delegate = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="delegations_received",
        verbose_name="المستخدم المفوَّض / السكرتارية",
    )
    delegation_type = models.CharField(
        "نوع التفويض",
        max_length=20,
        choices=DelegationType.choices,
        default=DelegationType.SECRETARIAT,
    )
    scope_unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="نطاق الوحدة التنظيمية",
    )
    allowed_actions = models.JSONField(
        "الإجراءات المسموح بها",
        default=list,
        help_text="قائمة أكواد الصلاحيات المسموح تنفيذها بالنيابة",
    )
    allow_confidential = models.BooleanField("يشمل المعاملات السرية", default=False)
    valid_from = models.DateTimeField("بداية التفويض")
    valid_to = models.DateTimeField("نهاية التفويض")
    is_active = models.BooleanField("ساري", default=True)
    revoked_at = models.DateTimeField("تاريخ الإلغاء", null=True, blank=True)
    revoked_reason = models.CharField("سبب الإلغاء", max_length=255, blank=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)

    class Meta:
        verbose_name = "تفويض / إنابة"
        verbose_name_plural = "التفويضات والإنابات"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.delegate.username} نيابة عن {self.delegator.username}"

    def is_currently_valid(self) -> bool:
        now = timezone.now()
        return (
            self.is_active
            and self.revoked_at is None
            and self.valid_from <= now <= self.valid_to
        )


class LoginAuditLog(models.Model):
    """سجل محاولات الدخول الناجحة والفاشلة لأغراض الأمان."""
    username_attempted = models.CharField("اسم المستخدم", max_length=150)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField("عنوان IP", null=True, blank=True)
    success = models.BooleanField("ناجحة", default=False)
    user_agent = models.CharField("المتصفح", max_length=255, blank=True)
    created_at = models.DateTimeField("التوقيت", auto_now_add=True)

    class Meta:
        verbose_name = "سجل محاولة دخول"
        verbose_name_plural = "سجل محاولات الدخول"
        ordering = ["-created_at"]
