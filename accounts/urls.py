from django.urls import path
from . import views, bulk

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("switch-user/", views.switch_user_view, name="switch_user"),
    path("users/", views.users_list, name="users_list"),
    path("users/bulk/", bulk.bulk_users, name="bulk_users"),
    path("users/bulk/template.<str:fmt>", bulk.bulk_template, name="bulk_template"),
    path("permissions-matrix/", views.permissions_matrix, name="permissions_matrix"),
    path("delegations/", views.delegations_view, name="delegations"),
]
