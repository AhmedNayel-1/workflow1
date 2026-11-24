"""
توجيه الروابط الرئيسي للمنظومة.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("organization/", include("organization.urls")),
    path("subjects/", include("subjects.urls")),
    path("documents/", include("documents.urls")),
    path("workflow/", include("workflow.urls")),
    path("committees/", include("committees.urls")),
    path("decisions/", include("decisions.urls")),
    path("notifications/", include("notifications.urls")),
    path("audit/", include("audit.urls")),
    path("reports/", include("reports.urls")),
    path("chat/", include("chat.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
