from django.contrib import admin
from .models import (
    Referral,
    ReferralRecipient,
    Task,
    WorkflowStepDefinition,
    WorkflowTemplate,
    WorkflowTemplateVersion,
)

admin.site.register(WorkflowTemplate)
admin.site.register(WorkflowTemplateVersion)
admin.site.register(WorkflowStepDefinition)
admin.site.register(Referral)
admin.site.register(ReferralRecipient)
admin.site.register(Task)
