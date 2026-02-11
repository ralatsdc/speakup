from django import forms
from django.contrib import admin, messages
from django.db import models
from django.http import HttpResponseRedirect
from django.urls import path

from .models import Meeting, MeetingSession, Role, MeetingRole, MeetingType, MeetingTypeItem, MeetingTypeSession, Session, Attendance
from .utils import send_meeting_reminders


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "is_speech_role", "points", "time_minutes", "in_person")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("name", "duration_minutes", "takes_roles")


class MeetingTypeSessionInline(admin.TabularInline):
    model = MeetingTypeSession
    extra = 1
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 30})},
    }


class MeetingTypeItemInline(admin.TabularInline):
    model = MeetingTypeItem
    extra = 1
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 30})},
    }

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "session":
            kwargs["queryset"] = Session.objects.filter(takes_roles=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(MeetingType)
class MeetingTypeAdmin(admin.ModelAdmin):
    inlines = [MeetingTypeSessionInline, MeetingTypeItemInline]


class MeetingSessionInline(admin.TabularInline):
    model = MeetingSession
    extra = 0
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 30})},
    }


class MeetingRoleInline(admin.TabularInline):
    model = MeetingRole
    extra = 0
    autocomplete_fields = ["user"]
    fields = ("session", "role", "user", "notes", "admin_notes", "sort_order")
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 30})},
    }


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("date", "meeting_type", "theme", "role_count_status")
    inlines = [MeetingSessionInline, MeetingRoleInline]
    change_form_template = "meetings/admin/meeting_change_form.html"

    def role_count_status(self, obj):
        filled = obj.roles.filter(user__isnull=False).count()
        total = obj.roles.count()
        return f"{filled}/{total} Roles Filled"

    role_count_status.short_description = "Staffing"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:meeting_id>/send-reminders/",
                self.admin_site.admin_view(self.process_reminders),
                name="meeting-reminders",
            ),
            path(
                "<int:meeting_id>/send-feedback/",
                self.admin_site.admin_view(self.process_feedback),
                name="meeting-feedback",
            ),
        ]
        return custom_urls + urls

    def process_reminders(self, request, meeting_id):
        meeting = self.get_object(request, meeting_id)
        count = send_meeting_reminders(meeting)
        self.message_user(
            request, f"Successfully queued {count} reminder emails.", messages.SUCCESS
        )
        return HttpResponseRedirect(f"../../{meeting_id}/change/")

    def process_feedback(self, request, meeting_id):
        from .utils import send_meeting_feedback

        meeting = self.get_object(request, meeting_id)
        feedback_count, guest_count = send_meeting_feedback(meeting)

        parts = []
        if feedback_count:
            parts.append(f"feedback to {feedback_count} members")
        if guest_count:
            parts.append(f"thank-you to {guest_count} guests")

        if parts:
            self.message_user(
                request, f"Sent {', '.join(parts)}.", messages.SUCCESS
            )
        else:
            self.message_user(
                request, "No feedback or guest emails to send.", messages.WARNING
            )

        return HttpResponseRedirect(f"../../{meeting_id}/change/")

    def response_change(self, request, obj):
        """Route the custom 'Send Reminders' and 'Send Feedback' buttons."""
        if "_send-reminders" in request.POST:
            return self.process_reminders(request, obj.pk)
        if "_send-feedback" in request.POST:
            return self.process_feedback(request, obj.pk)
        return super().response_change(request, obj)


@admin.register(MeetingRole)
class MeetingRoleAdmin(admin.ModelAdmin):
    list_display = ("meeting", "role", "user", "sort_order")
    list_filter = ("meeting", "role")
    list_editable = ("user", "sort_order")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("meeting", "who_attended", "guest_email", "timestamp")
    list_filter = ("meeting", ("user", admin.EmptyFieldListFilter))
    search_fields = ("guest_name", "guest_email")
    actions = ["convert_guest_to_user"]

    @admin.action(description="Convert selected guests to Users")
    def convert_guest_to_user(self, request, queryset):
        from .services import convert_guest_attendance_to_user

        created_count = 0
        linked_count = 0

        for attendance in queryset:
            user, created = convert_guest_attendance_to_user(attendance)
            if user and created:
                created_count += 1
            elif user:
                linked_count += 1

        self.message_user(
            request,
            f"Created {created_count} new users and linked {linked_count} existing users. "
            f"New users will need to reset their password via the login page.",
            messages.SUCCESS,
        )

    def who_attended(self, obj):
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name} ({'Member' if not obj.user.is_guest else 'Guest User'})"
        return f"{obj.guest_name} (Walk-in)"
