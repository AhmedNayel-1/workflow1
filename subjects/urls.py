from django.urls import path
from . import views

app_name = "subjects"

urlpatterns = [
    path("", views.subject_list, name="subject_list"),
    path("create/", views.subject_create, name="subject_create"),
    path("<int:subject_id>/", views.subject_detail, name="subject_detail"),
    path("<int:subject_id>/preview-json/", views.subject_preview_json, name="subject_preview_json"),
    path("<int:subject_id>/action-options/", views.subject_action_options, name="subject_action_options"),
    path("<int:subject_id>/suspension-request/", views.suspension_request, name="suspension_request"),
    path("<int:subject_id>/action/", views.subject_quick_action, name="subject_quick_action"),
    path("<int:subject_id>/referrals-manage/", views.subject_referrals_manage, name="subject_referrals_manage"),
    path("<int:subject_id>/timeline-json/", views.subject_timeline_json, name="subject_timeline_json"),
    path("action-file/<int:file_id>/", views.subject_action_file, name="subject_action_file"),
    path("<int:subject_id>/export-pdf/", views.subject_export_pdf, name="subject_export_pdf"),
    path("memos/<int:memo_id>/print/", views.memo_print, name="memo_print"),
    path("memos/<int:memo_id>/export-pdf/", views.memo_export_pdf, name="memo_export_pdf"),
]
