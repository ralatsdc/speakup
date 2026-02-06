from django.urls import path
from . import views

urlpatterns = [
    path("", views.upcoming_meetings, name="upcoming_meetings"),
    path("role/<int:role_id>/toggle/", views.toggle_role, name="toggle_role"),
]
