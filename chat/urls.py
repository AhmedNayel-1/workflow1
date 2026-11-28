from django.urls import path
from . import views

app_name = "chat"

urlpatterns = [
    path("state/", views.chat_state, name="state"),
    path("direct/", views.create_direct, name="direct"),
    path("groups/", views.create_group, name="groups"),
    path("messages/", views.send_message, name="messages"),
    path("read/", views.mark_read, name="read"),
    path("attachment/<int:msg_id>/", views.chat_attachment, name="attachment"),
]
