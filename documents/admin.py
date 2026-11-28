from django.contrib import admin
from .models import Attachment, Document, DocumentVersion, SubjectDocumentLink

admin.site.register(Document)
admin.site.register(SubjectDocumentLink)
admin.site.register(DocumentVersion)
admin.site.register(Attachment)
