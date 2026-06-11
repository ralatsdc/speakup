from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.urls import path
from import_export.admin import ImportExportModelAdmin

from .emails import send_welcome_email
from .models import User
from .resources import UserResource
from .views import activity_report, activity_report_detail

DEFAULT_PASSWORD = "Speak-Up-2026"


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["password1"] = DEFAULT_PASSWORD
        self.initial["password2"] = DEFAULT_PASSWORD
        self.fields["password1"].widget.render_value = True
        self.fields["password2"].widget.render_value = True
        # Email is unique at the DB level — make the admin form require it
        # explicitly so the error is friendly, not an IntegrityError.
        self.fields["email"].required = True


@admin.action(description="Make Guest")
def make_guest(modeladmin, request, queryset):
    count = queryset.update(is_guest=True)
    modeladmin.message_user(request, f"{count} user(s) marked as guest.")


@admin.action(description="Remove Guest")
def remove_guest(modeladmin, request, queryset):
    count = queryset.update(is_guest=False)
    modeladmin.message_user(request, f"{count} user(s) unmarked as guest.")


@admin.action(description="Make Officer")
def make_officer(modeladmin, request, queryset):
    # Iterate + save() so the post_save signal (members/signals.py) fires
    # and grants is_staff + Officers-group membership. queryset.update()
    # would silently skip the sync.
    count = 0
    for user in queryset:
        if not user.is_officer:
            user.is_officer = True
            user.save(update_fields=["is_officer"])
            count += 1
    modeladmin.message_user(request, f"{count} user(s) marked as officer.")


@admin.action(description="Remove Officer")
def remove_officer(modeladmin, request, queryset):
    count = 0
    for user in queryset:
        if user.is_officer:
            user.is_officer = False
            user.save(update_fields=["is_officer"])
            count += 1
    modeladmin.message_user(request, f"{count} user(s) unmarked as officer.")


@admin.action(description="Make Active")
def make_active(modeladmin, request, queryset):
    count = queryset.update(is_active=True)
    modeladmin.message_user(request, f"{count} user(s) marked as active.")


@admin.action(description="Remove Active")
def remove_active(modeladmin, request, queryset):
    queryset = queryset.exclude(pk=request.user.pk)
    count = queryset.update(is_active=False)
    modeladmin.message_user(request, f"{count} user(s) unmarked as active.")


@admin.action(description="Send welcome email")
def send_welcome_emails(modeladmin, request, queryset):
    sent = 0
    skipped = 0
    for user in queryset:
        if user.email:
            sent += send_welcome_email(user)
        else:
            skipped += 1
    msg = f"Welcome email sent to {sent} member(s)."
    if skipped:
        msg += f" Skipped {skipped} without an email address."
    modeladmin.message_user(request, msg)


class CustomUserAdmin(ImportExportModelAdmin, UserAdmin):
    # Custom changelist template injects an "Activity report" link in the
    # object-tools row, alongside Django's stock "Add user" button.
    change_list_template = "members/admin/user_change_list.html"
    add_form = CustomUserCreationForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "password1", "password2"),
            },
        ),
    )
    resource_class = UserResource # Link the logic we just wrote
    # Add your custom fields to the 'fieldsets' so you can edit them
    fieldsets = UserAdmin.fieldsets + (
        (
            "Toastmasters Profile",
            {
                "fields": (
                    "is_guest",
                    "join_date",
                    "notes",
                    "phone_number",
                    "is_officer",
                    "mentor",
                )
            },
        ),
    )

    # Columns to show in the list view
    list_display = (
        "username",
        "first_name",
        "last_name",
        "is_guest",
        "is_officer",
        "is_active",
        "email",
    )

    # Filters on the right sidebar (Find guests quickly!)
    list_filter = ("is_guest", "is_officer", "is_active")

    # Fields a non-superuser (officer) may edit when changing a user: the
    # member roster minus every privilege control. is_staff / is_superuser /
    # is_officer / groups / user_permissions are absent, so an officer can
    # manage members but can never grant admin access or escalate. Fields not
    # in the form are left untouched on save, so existing flags are preserved.
    officer_fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        ("Status", {"fields": ("is_active",)}),
        ("Toastmasters Profile", {
            "fields": ("is_guest", "join_date", "notes", "phone_number", "mentor")}),
    )

    def get_fieldsets(self, request, obj=None):
        # The add form (obj is None) is already privilege-free; superusers keep
        # the full set; officers editing an existing user get the safe set.
        if obj is not None and not request.user.is_superuser:
            return self.officer_fieldsets
        return super().get_fieldsets(request, obj)

    def get_actions(self, request):
        # Promoting/demoting officers grants admin access — superuser-only.
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("make_officer", None)
            actions.pop("remove_officer", None)
        return actions

    def has_import_permission(self, request):
        # CSV import can set is_staff / is_officer, so it stays superuser-only.
        return request.user.is_superuser

    # Search bar capability
    search_fields = ("username", "first_name", "last_name", "email")

    actions = [make_guest, remove_guest, make_officer, remove_officer, make_active, remove_active, send_welcome_emails]

    def get_urls(self):
        urls = super().get_urls()
        # Custom URLs go before the default ones — Django routes top-down,
        # and the default ``<path:object_id>/change/`` would otherwise eat
        # the "activity-report" segment.
        custom = [
            path(
                "activity-report/",
                self.admin_site.admin_view(activity_report),
                name="members_user_activity_report",
            ),
            path(
                "activity-report/<int:user_id>/",
                self.admin_site.admin_view(activity_report_detail),
                name="members_user_activity_report_detail",
            ),
        ]
        return custom + urls



# admin.site.unregister(User) # Unregister the default if needed, though we didn't use the default
admin.site.register(User, CustomUserAdmin)
