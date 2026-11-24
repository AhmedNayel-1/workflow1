"""
نموذج الهيكل التنظيمي الديناميكي متعدد القطاعات.
يدعم إضافة مستويات تنظيمية مرنة وفصل الموظف عن المنصب وحفظ تاريخ التنقلات.
"""
from django.db import models


class Company(models.Model):
    """الشركة القابضة والشركات الشقيقة الموازية (مثل شركة غرب الدلتا لإنتاج الكهرباء)."""
    code = models.CharField("كود الشركة", max_length=30, unique=True)
    name = models.CharField("اسم الشركة", max_length=200)
    short_name = models.CharField("الاسم المختصر", max_length=100, blank=True)
    is_holding = models.BooleanField("الشركة القابضة الأم", default=False)
    parent_company = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subsidiaries",
        verbose_name="الشركة القابضة",
    )
    is_active = models.BooleanField("مفعلة", default=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)

    class Meta:
        verbose_name = "شركة"
        verbose_name_plural = "الشركات"
        ordering = ["-is_holding", "id"]

    def __str__(self):
        return self.name


class Sector(models.Model):
    """القطاع (مثل: قطاع الموارد البشرية، قطاع الإنتاج، الشئون المالية)."""
    code = models.CharField("كود القطاع", max_length=30, unique=True)
    name = models.CharField("اسم القطاع", max_length=150)
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sectors",
        verbose_name="الشركة التابعة لها",
    )
    is_active = models.BooleanField("مفعل", default=True)
    created_at = models.DateTimeField("تاريخ الإنشاء", auto_now_add=True)

    class Meta:
        verbose_name = "قطاع"
        verbose_name_plural = "القطاعات"
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrgUnitType(models.Model):
    """أنواع الوحدات التنظيمية القابلة للتعديل (رئاسة مجلس، قطاع، إدارة عامة، إدارة، قسم...)."""
    code = models.CharField("الكود", max_length=30, unique=True)
    name = models.CharField("نوع الوحدة", max_length=100)
    level_order = models.PositiveSmallIntegerField("الترتيب الهرمي", default=1)

    class Meta:
        verbose_name = "نوع وحدة تنظيمية"
        verbose_name_plural = "أنواع الوحدات التنظيمية"
        ordering = ["level_order"]

    def __str__(self):
        return self.name


class OrgUnit(models.Model):
    """الوحدة التنظيمية الديناميكية دون تثبيت عدد مستويات داخل الكود."""
    code = models.CharField("الكود التنظيمي", max_length=40, unique=True)
    name = models.CharField("اسم الوحدة", max_length=180)
    unit_type = models.ForeignKey(
        OrgUnitType,
        on_delete=models.PROTECT,
        verbose_name="نوع الوحدة",
    )
    sector = models.ForeignKey(
        Sector,
        on_delete=models.PROTECT,
        related_name="org_units",
        verbose_name="القطاع التابع له",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="الوحدة الأب",
    )
    manager_employee = models.ForeignKey(
        "Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_units",
        verbose_name="المسؤول الحالي",
    )
    is_active = models.BooleanField("مفعل", default=True)
    effective_from = models.DateField("تاريخ بدء التبعية", null=True, blank=True)
    effective_to = models.DateField("تاريخ انتهاء التبعية", null=True, blank=True)

    class Meta:
        verbose_name = "وحدة تنظيمية"
        verbose_name_plural = "الوحدات التنظيمية"
        ordering = ["unit_type__level_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.sector.name})"

    def get_descendant_ids(self) -> set[int]:
        """إرجاع معرّفات هذه الوحدة وجميع الوحدات الأدنى التابعة لها داخل نفس القطاع."""
        ids = {self.id}
        frontier = [self.id]
        while frontier:
            children = list(
                OrgUnit.objects.filter(parent_id__in=frontier, is_active=True).values_list("id", flat=True)
            )
            new_ids = [cid for cid in children if cid not in ids]
            ids.update(new_ids)
            frontier = new_ids
        return ids

    def is_ancestor_of(self, target_unit: "OrgUnit") -> bool:
        """هل هذه الوحدة أعلى هرمياً من الوحدة المستهدفة؟"""
        current = target_unit.parent
        visited = set()
        while current is not None and current.id not in visited:
            if current.id == self.id:
                return True
            visited.add(current.id)
            current = current.parent
        return False


class Employee(models.Model):
    """بيانات الموظف (منفصلة عن حساب المستخدم وعن المنصب التنظيمي)."""
    employee_number = models.CharField("الرقم الوظيفي", max_length=40, unique=True)
    full_name = models.CharField("الاسم الكامل", max_length=180)
    job_title = models.CharField("المسمى الوظيفي", max_length=150)
    current_unit = models.ForeignKey(
        OrgUnit,
        on_delete=models.PROTECT,
        related_name="employees",
        verbose_name="الوحدة التنظيمية الحالية",
    )
    internal_phone = models.CharField("الهاتف الداخلي", max_length=40, blank=True)
    email = models.EmailField("البريد الداخلي", blank=True)
    is_active = models.BooleanField("على رأس العمل", default=True)

    class Meta:
        verbose_name = "موظف"
        verbose_name_plural = "الموظفون"
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.employee_number})"


class PositionAssignment(models.Model):
    """سجل تاريخي لتنقلات الموظفين بين الوحدات والمناصب."""
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="position_history",
        verbose_name="الموظف",
    )
    org_unit = models.ForeignKey(
        OrgUnit,
        on_delete=models.PROTECT,
        verbose_name="الوحدة التنظيمية",
    )
    position_title = models.CharField("المنصب / الوظيفة", max_length=150)
    start_date = models.DateField("تاريخ البداية")
    end_date = models.DateField("تاريخ النهاية", null=True, blank=True)
    is_current = models.BooleanField("المنصب الحالي", default=True)
    notes = models.TextField("ملاحظات النقل", blank=True)

    class Meta:
        verbose_name = "تكليف منصب تاريخي"
        verbose_name_plural = "سجل المناصب والتنقلات"
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.employee.full_name} - {self.position_title}"
