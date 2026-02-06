from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string
from .models import Meeting, Role, MeetingRole, MeetingType, MeetingTypeItem, Attendance

User = get_user_model()


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
        created_count = 0
        existing_count = 0

        for attendance in queryset:
            # Skip if already linked to a user
            if attendance.user:
                continue

            # Skip if no email provided
            if not attendance.guest_email:
                continue

            email = attendance.guest_email.strip().lower()
            name_parts = attendance.guest_name.strip().split(" ", 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ""

            # Check if user already exists (by email)
            if User.objects.filter(email=email).exists():
                # Just link the existing user to this attendance record
                user = User.objects.get(email=email)
                attendance.user = user
                attendance.save()
                existing_count += 1
            else:
                # Create new User
                # Username strategy: use email part or first.last
                username = email.split("@")[0]

                # Ensure username uniqueness
                counter = 1
                base_username = username
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1

                # Generate a temp password
                temp_password = "Welcome123!"

                new_user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=temp_password,
                    first_name=first_name,
                    last_name=last_name,
                    is_guest=True,  # Mark as Guest in your custom field
                )

                # Link the attendance record to the new user
                attendance.user = new_user
                attendance.save()
                created_count += 1

        self.message_user(
            request,
            f"Successfully created {created_count} new users and linked {existing_count} existing users. "
            f"Default password is 'Welcome123!'",
            messages.SUCCESS,
        )

    def who_attended(self, obj):
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name} ({'Member' if not obj.user.is_guest else 'Guest User'})"
        return f"{obj.guest_name} (Walk-in)"
