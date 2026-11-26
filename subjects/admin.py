from django.contrib import admin
from .models import (
    Annotation,
    NoticeRecord,
    OutgoingCorrespondence,
    Memo,
    Subject,
    SubjectAccessGrant,
    SubjectStatusHistory,
    SubjectSuspension,
)

admin.site.register(Subject)
admin.site.register(SubjectAccessGrant)
admin.site.register(SubjectSuspension)
admin.site.register(SubjectStatusHistory)
admin.site.register(Memo)
admin.site.register(Annotation)

admin.site.register(NoticeRecord)
admin.site.register(OutgoingCorrespondence)
