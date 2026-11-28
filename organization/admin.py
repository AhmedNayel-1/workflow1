from django.contrib import admin
from .models import Employee, OrgUnit, OrgUnitType, PositionAssignment, Sector

admin.site.register(Sector)
admin.site.register(OrgUnitType)
admin.site.register(OrgUnit)
admin.site.register(Employee)
admin.site.register(PositionAssignment)


from .models import ExternalEntity  # noqa: E402


@admin.register(ExternalEntity)
class ExternalEntityAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")
