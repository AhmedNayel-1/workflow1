from django.contrib import admin
from .models import Committee, CommitteeAgendaItem, CommitteeMeeting

admin.site.register(Committee)
admin.site.register(CommitteeMeeting)
admin.site.register(CommitteeAgendaItem)
