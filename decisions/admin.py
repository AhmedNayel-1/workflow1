from django.contrib import admin
from .models import Decision, DecisionDistribution, DecisionExecutionItem

admin.site.register(Decision)
admin.site.register(DecisionDistribution)
admin.site.register(DecisionExecutionItem)
