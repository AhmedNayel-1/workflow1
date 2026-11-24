from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    Delegation,
    LoginAuditLog,
    PermissionCode,
    Role,
    RolePermission,
    User,
    UserRoleAssignment,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("الربط التنظيمي", {"fields": ("employee", "job_display_title", "is_secretariat", "is_system_admin")}),
    )


admin.site.register(PermissionCode)
admin.site.register(Role)
admin.site.register(RolePermission)
admin.site.register(UserRoleAssignment)
admin.site.register(Delegation)
admin.site.register(LoginAuditLog)
