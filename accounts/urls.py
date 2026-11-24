from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("switch-user/", views.switch_user_view, name="switch_user"),
    path("users/", views.users_list, name="users_list"),
    path("permissions-matrix/", views.permissions_matrix, name="permissions_matrix"),
    path("delegations/", views.delegations_view, name="delegations"),
]
