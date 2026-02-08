from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import path

from .models import Meeting, Role, MeetingRole, MeetingType, MeetingTypeItem, Attendance
from .utils import send_meeting_reminders


# 1. Setup the Role Admin
@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "is_speech_role", "points")


# 1. Helper to define the template items (Speaker x3)
class MeetingTypeItemInline(admin.TabularInline):
    model = MeetingTypeItem
    extra = 1


@admin.register(MeetingType)
class MeetingTypeAdmin(admin.ModelAdmin):
    inlines = [MeetingTypeItemInline]  # Allows editing quantities inside the Type page


# 2. Setup the Inline
# This allows you to edit MeetingRoles *inside* the Meeting page
class MeetingRoleInline(admin.TabularInline):
    model = MeetingRole
    extra = 0  # Don't show extra empty rows by default
    autocomplete_fields = [
        "user"
    ]  # Great if you have 50+ members (requires search_fields on User)
    fields = ("role", "user", "notes", "admin_notes", "sort_order")


# 3. Setup the Meeting Admin
@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("date", "meeting_type", "theme", "role_count_status")
    inlines = [MeetingRoleInline]  # Connects the inline here
    change_form_template = (
        "meetings/admin/meeting_change_form.html"  # We need to extend the template
    )

    # A custom helper to see at a glance if the meeting is fully staffed
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
        # The logic to trigger the email
        meeting = self.get_object(request, meeting_id)
        count = send_meeting_reminders(meeting)
        self.message_user(
            request, f"Successfully queued {count} reminder emails.", messages.SUCCESS
        )
        return HttpResponseRedirect(f"../../{meeting_id}/change/")

    # NEW: Handle the Feedback button
    def process_feedback(self, request, meeting_id):
        from .utils import (
            send_meeting_feedback,
        )  # Import inside method to avoid circular imports

        meeting = self.get_object(request, meeting_id)

        count = send_meeting_feedback(meeting)

        if count > 0:
            self.message_user(
                request, f"Sent feedback emails to {count} members.", messages.SUCCESS
            )
        else:
            self.message_user(
                request, "No feedback notes found to send.", messages.WARNING
            )

        return HttpResponseRedirect(f"../../{meeting_id}/change/")

    # Add the button to the UI
    def response_change(self, request, obj):
        if "_send-reminders" in request.POST:
            return self.process_reminders(request, obj.pk)
        if "_send-feedback" in request.POST:
            return self.process_feedback(request, obj.pk)
        return super().response_change(request, obj)


# 2. Update MeetingRoleAdmin (Optional: add sort_order to list_editable)
@admin.register(MeetingRole)
class MeetingRoleAdmin(admin.ModelAdmin):
    list_display = ("meeting", "role", "user", "sort_order")
    list_filter = ("meeting", "role")
    list_editable = ("user", "sort_order")  # Allow reordering/assigning from list view


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("meeting", "who_attended", "guest_email", "timestamp")
    list_filter = ("meeting", ("user", admin.EmptyFieldListFilter))
    search_fields = ("guest_name", "guest_email")
    actions = ["convert_guest_to_user"]  # Enable the action

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
