from django.contrib import admin
from .models import ActivityLog, AuditLog

admin.site.register(ActivityLog)
admin.site.register(AuditLog)
