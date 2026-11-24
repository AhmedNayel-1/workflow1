from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("archive-search/", views.archive_quick_search, name="archive_search"),
    path("guide/", views.user_guide_view, name="user_guide"),
    path("db-admin/", views.database_admin_view, name="db_admin"),
    path("search/", views.advanced_search, name="search"),
    path("settings/", views.system_settings, name="settings"),
]
