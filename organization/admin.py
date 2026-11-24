from django.contrib import admin
from .models import Employee, OrgUnit, OrgUnitType, PositionAssignment, Sector

admin.site.register(Sector)
admin.site.register(OrgUnitType)
admin.site.register(OrgUnit)
admin.site.register(Employee)
admin.site.register(PositionAssignment)
