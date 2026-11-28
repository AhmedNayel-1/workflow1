from django.urls import path
from . import views

app_name = "workflow"

urlpatterns = [
    path("referrals/", views.referral_inbox, name="referral_inbox"),
    path("referrals/create/<int:subject_id>/", views.referral_create, name="referral_create"),
    path("referrals/<int:recipient_id>/respond/", views.referral_respond, name="referral_respond"),
    path("referrals/<int:recipient_id>/reject/", views.referral_reject, name="referral_reject"),
    path("referrals/<int:referral_id>/withdraw/", views.referral_withdraw, name="referral_withdraw"),
    path("referrals/<int:recipient_id>/reassign/", views.referral_reassign, name="referral_reassign"),
    path("subjects/<int:subject_id>/apply-template/", views.apply_workflow_template, name="apply_template"),
    path("tasks/", views.task_list, name="task_list"),
    path("tasks/create/<int:subject_id>/", views.task_create, name="task_create"),
    path("tasks/<int:task_id>/update/", views.task_update_status, name="task_update_status"),
    path("templates/", views.workflow_templates_list, name="templates_list"),
]

