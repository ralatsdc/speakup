from django.urls import path
from . import views

urlpatterns = [
    path("", views.upcoming_meetings, name="upcoming_meetings"),
    path("role/<int:role_id>/toggle/", views.toggle_role, name="toggle_role"),

    # Kiosk Routes
    path("kiosk/", views.checkin_kiosk, name="checkin_kiosk"),
    path(
        "kiosk/<int:meeting_id>/member/<int:user_id>/",
        views.checkin_member,
        name="checkin_member",
    ),
    path("kiosk/<int:meeting_id>/guest/", views.checkin_guest, name="checkin_guest"),
]
