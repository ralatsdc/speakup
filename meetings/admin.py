from django.contrib import admin
from .models import Meeting, Role, MeetingRole, MeetingType, Attendance


# 1. Setup the Role Admin
@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "is_speech_role", "points")


@admin.register(MeetingType)
class MeetingTypeAdmin(admin.ModelAdmin):
    # This allows you to select multiple roles nicely
    filter_horizontal = ("default_roles",)


# 2. Setup the Inline
# This allows you to edit MeetingRoles *inside* the Meeting page
class MeetingRoleInline(admin.TabularInline):
    model = MeetingRole
    extra = 0  # Don't show extra empty rows by default
    autocomplete_fields = [
        "user"
    ]  # Great if you have 50+ members (requires search_fields on User)


# 3. Setup the Meeting Admin
@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "meeting_type",
        "theme",
        "role_count_status",
    )  # Added meeting_type
    list_display = ("date", "theme", "role_count_status")
    inlines = [MeetingRoleInline]  # Connects the inline here

    # A custom helper to see at a glance if the meeting is fully staffed
    def role_count_status(self, obj):
        filled = obj.roles.filter(user__isnull=False).count()
        total = obj.roles.count()
        return f"{filled}/{total} Roles Filled"

    role_count_status.short_description = "Staffing"


# 4. Register MeetingRole separately too (optional, but good for debugging)
@admin.register(MeetingRole)
class MeetingRoleAdmin(admin.ModelAdmin):
    list_display = ("meeting", "role", "user")
    list_filter = ("meeting", "role")
