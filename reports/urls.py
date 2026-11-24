from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("", views.reports_dashboard, name="dashboard"),
    path("<slug:slug>/", views.report_detail, name="report_detail"),
]
