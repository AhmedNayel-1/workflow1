from django.urls import path
from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_center, name="center"),
    path("drawer-state/", views.drawer_state, name="drawer_state"),
    path("mark-read/", views.mark_read_api, name="mark_read_api"),
]
