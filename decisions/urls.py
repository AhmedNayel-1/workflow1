from django.urls import path
from . import views

app_name = "decisions"

urlpatterns = [
    path("", views.decision_list, name="decision_list"),
    path("create/<int:subject_id>/", views.decision_create, name="decision_create"),
    path("<int:decision_id>/", views.decision_detail, name="decision_detail"),
    path("<int:decision_id>/print/", views.decision_print, name="decision_print"),
]
