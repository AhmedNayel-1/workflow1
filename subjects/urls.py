from django.urls import path
from . import views

app_name = "subjects"

urlpatterns = [
    path("", views.subject_list, name="subject_list"),
    path("create/", views.subject_create, name="subject_create"),
    path("<int:subject_id>/", views.subject_detail, name="subject_detail"),
    path("<int:subject_id>/preview-json/", views.subject_preview_json, name="subject_preview_json"),
    path("<int:subject_id>/export-pdf/", views.subject_export_pdf, name="subject_export_pdf"),
    path("memos/<int:memo_id>/print/", views.memo_print, name="memo_print"),
    path("memos/<int:memo_id>/export-pdf/", views.memo_export_pdf, name="memo_export_pdf"),
]
