from django.urls import path
from . import views

urlpatterns = [
    # Role sign-up page
    path("signups/", views.role_signups, name="role_signups"),
    # Role signups
    path(
        "role/<int:role_id>/signup-form/",
        views.signup_role_form,
        name="signup_role_form",
    ),
    path("role/<int:role_id>/toggle/", views.toggle_role, name="toggle_role"),
    path("role/<int:role_id>/edit/", views.save_role_details, name="save_role_details"),
    # Meeting agenda (public)
    path("meeting/<int:meeting_id>/agenda/", views.meeting_agenda, name="meeting_agenda"),
    path(
        "meeting/<int:meeting_id>/agenda/download/",
        views.meeting_agenda_download,
        name="meeting_agenda_download",
    ),
    # Kiosk Routes
    path("kiosk/", views.checkin_kiosk, name="checkin_kiosk"),
    path(
        "kiosk/<int:meeting_id>/member/<int:user_id>/",
        views.checkin_member,
        name="checkin_member",
    ),
    path("kiosk/<int:meeting_id>/guest/", views.checkin_guest, name="checkin_guest"),
]
