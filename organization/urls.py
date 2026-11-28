from django.urls import path
from . import views

app_name = "organization"

urlpatterns = [
    path("", views.org_tree, name="org_tree"),
    path("move-unit/", views.move_unit_view, name="move_unit"),
    path("move-user/", views.move_user_view, name="move_user"),
]
