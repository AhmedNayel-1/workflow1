from django.urls import path
from . import views

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="document_list"),
    path("create/", views.document_create, name="document_create"),
    path("<int:doc_id>/", views.document_detail, name="document_detail"),
    path("<int:doc_id>/export-pdf/", views.document_export_pdf, name="document_export_pdf"),
    path("attachments/<int:attachment_id>/download/", views.attachment_download, name="attachment_download"),
    path("attachments/<int:attachment_id>/preview/", views.attachment_preview, name="attachment_preview"),
]
