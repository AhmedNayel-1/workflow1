from django.urls import path
from . import views

app_name = "committees"

urlpatterns = [
    path("", views.committee_list, name="committee_list"),
    path("meetings/<int:meeting_id>/", views.meeting_detail, name="meeting_detail"),
    path("meetings/<int:meeting_id>/print/", views.minutes_print, name="minutes_print"),
]
