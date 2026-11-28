from django.contrib import admin
from .models import (
    ConfidentialityLevel,
    DocumentType,
    PriorityLevel,
    RetentionPolicy,
    SuspensionReason,
    SystemErrorLog,
    SystemSequence,
    TransactionType,
)

admin.site.register(ConfidentialityLevel)
admin.site.register(PriorityLevel)
admin.site.register(TransactionType)
admin.site.register(DocumentType)
admin.site.register(SuspensionReason)
admin.site.register(RetentionPolicy)
admin.site.register(SystemSequence)
admin.site.register(SystemErrorLog)
