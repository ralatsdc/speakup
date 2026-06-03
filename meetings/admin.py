from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.db import models
from django.db.models import OuterRef, Subquery
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from urllib.parse import urlencode

from .models import (
    Attendance,
    Meeting,
    MeetingRole,
    MeetingSession,
    MeetingType,
    MeetingTypeItem,
    MeetingTypeSession,
    Role,
    RoleGuideEmailLog,
    Session,
)
def _review_url(workflow, **params):
    """URL of the shared review-before-send page for a workflow + target ids."""
    return reverse("email_review") + "?" + urlencode({"workflow": workflow, **params})


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "shows_pathways_fields",
        "is_evaluator_role",
        "is_evaluated_role",
        "points",
        "time_minutes",
        "has_guide",
    )
    list_filter = ("shows_pathways_fields", "is_evaluator_role", "is_evaluated_role")

    @admin.display(boolean=True, description="Guide?")
    def has_guide(self, obj):
        return bool(obj.guidance_document)


@admin.register(RoleGuideEmailLog)
class RoleGuideEmailLogAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "sent_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "role__name")
    readonly_fields = ("sent_at",)


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
    # Sessions are copied from the MeetingType template at creation and
    # almost never change per-meeting. Collapse the whole inline so it
    # doesn't take page space until an officer explicitly needs to edit
    # it.
    classes = ("collapse",)
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 30})},
    }


class MeetingRoleInline(admin.StackedInline):
    model = MeetingRole
    fk_name = "meeting"
    extra = 0
    autocomplete_fields = ["user"]
    # Custom inline template inserts a section header before each new
    # session group (see meetings/templates/admin/edit_inline/
    # meetings_meetingrole_stacked.html).
    template = "admin/edit_inline/meetings_meetingrole_stacked.html"
    # Stacked layout per MeetingRole: dropdowns cluster on row 1, evaluates
    # sits on its own row directly below them, then numeric. Notes +
    # admin_notes live in a separate collapsed fieldset so they don't
    # take vertical space until clicked open.
    fieldsets = (
        (None, {
            "fields": (
                ("session", "role", "user", "in_person"),
                "evaluates",
                ("pathways_path", "pathways_level", "pathways_project"),
                "time_minutes",
                # sort_order is hidden by inline_drag_sort.css — drag-to-
                # reorder writes to it via JS. Kept in the fieldset so the
                # form submits the updated value.
                "sort_order",
            ),
        }),
        ("Notes", {
            "classes": ("collapse",),
            "fields": ("notes", "admin_notes"),
        }),
    )
    formfield_overrides = {
        models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 60})},
    }

    class Media:
        # Live-toggles for `evaluates` (only on evaluator roles) and the
        # three Pathways fields (only on speech roles); collapsible row
        # headers; styling for session-group headers inserted by the
        # custom inline template. Toggles are visual only; server-side
        # MeetingRole.clean() / model validation still enforce the rules,
        # so JS-disabled clients degrade safely.
        css = {
            "all": (
                "meetings/admin/evaluator_pairing.css",
                "meetings/admin/pathways_visibility.css",
                "meetings/admin/session_grouping.css",
                "meetings/admin/row_collapse.css",
                "meetings/admin/inline_filter.css",
                "meetings/admin/inline_drag_sort.css",
            )
        }
        js = (
            "meetings/admin/evaluator_pairing.js",
            "meetings/admin/pathways_visibility.js",
            "meetings/admin/row_collapse.js",
            "meetings/admin/inline_filter.js",
            # SortableJS via CDN (Django Media supports absolute URLs).
            # Loaded before inline_drag_sort.js, which depends on the
            # `Sortable` global.
            "https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js",
            "meetings/admin/inline_drag_sort.js",
        )

    def get_queryset(self, request):
        # Order rows so they cluster under their session header on the
        # change form. Per-meeting session order lives on MeetingSession;
        # MeetingRole.session points at the reusable Session, so subquery
        # for the matching MeetingSession.sort_order. Null/missing
        # sessions sort first (templates can put them under a "no
        # session" header).
        return (
            super()
            .get_queryset(request)
            .annotate(
                _session_order=Subquery(
                    MeetingSession.objects.filter(
                        meeting=OuterRef("meeting"),
                        session=OuterRef("session"),
                    ).values("sort_order")[:1]
                )
            )
            .order_by("_session_order", "sort_order", "id")
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "evaluates":
            # Limit the picker to MeetingRoles on the parent meeting whose
            # role is flagged as evaluated (Speaker, Ranter, …). The parent
            # meeting's PK is in the admin URL.
            parent_id = request.resolver_match.kwargs.get("object_id")
            if parent_id:
                kwargs["queryset"] = (
                    MeetingRole.objects
                    .filter(meeting_id=parent_id, role__is_evaluated_role=True)
                    .select_related("role", "user")
                )
            else:
                kwargs["queryset"] = MeetingRole.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("date", "meeting_type", "theme", "role_count_status")
    inlines = [MeetingSessionInline, MeetingRoleInline]
    change_form_template = "meetings/admin/meeting_change_form.html"
    # Word of the day is the only field that changes regularly after a
    # meeting is created from its template; everything else (date,
    # meeting_type, theme, zoom_link) is set once and rarely touched.
    # Surface word_of_the_day on its own, tuck the rest behind a
    # collapsed section.
    fieldsets = (
        (None, {
            "fields": ("word_of_the_day",),
        }),
        ("Meeting details", {
            # "meeting-admin-section" is a marker class read by
            # meeting_change_form.css → "Unified section headers" to
            # repaint this fieldset's h2 in the lighter banner hue.
            # The other fieldset on the form (Notes, inside each
            # MeetingRole row) intentionally stays Django-default.
            "classes": ("collapse", "meeting-admin-section"),
            "fields": ("meeting_type", "date", "theme", "zoom_link"),
        }),
    )

    class Media:
        # Tightens inline row density and pins the submit area to the
        # bottom of the viewport so officers don't scroll past 20 inline
        # rows to save or run an action.
        css = {"all": ("meetings/admin/meeting_change_form.css",)}

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
            path(
                "<int:meeting_id>/import-zoom-registrants/",
                self.admin_site.admin_view(self.process_zoom_import),
                name="meeting-zoom-import",
            ),
        ]
        return custom_urls + urls

    def process_reminders(self, request, meeting_id):
        return HttpResponseRedirect(_review_url("reminders", meeting=meeting_id))

    def process_feedback(self, request, meeting_id):
        return HttpResponseRedirect(_review_url("feedback", meeting=meeting_id))

    def process_zoom_import(self, request, meeting_id):
        # Feature is currently disabled — the underlying code is preserved
        # in meetings/zoom.py for if/when the registration flow comes back.
        if not settings.ZOOM_REGISTRATION_ENABLED:
            self.message_user(
                request,
                "Zoom registrant import is disabled "
                "(set ZOOM_REGISTRATION_ENABLED=true to re-enable).",
                messages.WARNING,
            )
            return HttpResponseRedirect(f"../../{meeting_id}/change/")

        from .zoom import import_zoom_registrants

        meeting = self.get_object(request, meeting_id)

        if not meeting.zoom_link:
            self.message_user(
                request, "This meeting has no Zoom link set.", messages.ERROR
            )
            return HttpResponseRedirect(f"../../{meeting_id}/change/")

        try:
            members_count, guests_count, skipped_count = import_zoom_registrants(meeting)
        except Exception as e:
            self.message_user(request, f"Zoom import failed: {e}", messages.ERROR)
            return HttpResponseRedirect(f"../../{meeting_id}/change/")

        parts = []
        if members_count:
            parts.append(f"{members_count} members")
        if guests_count:
            parts.append(f"{guests_count} guests")
        if skipped_count:
            parts.append(f"{skipped_count} skipped (duplicates)")

        if parts:
            self.message_user(
                request,
                f"Zoom import complete: {', '.join(parts)}.",
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request, "No registrants found to import.", messages.WARNING
            )

        return HttpResponseRedirect(f"../../{meeting_id}/change/")

    def response_change(self, request, obj):
        """Route custom action buttons."""
        if "_send-reminders" in request.POST:
            return self.process_reminders(request, obj.pk)
        if "_send-feedback" in request.POST:
            return self.process_feedback(request, obj.pk)
        if "_import-zoom" in request.POST:
            # process_zoom_import enforces ZOOM_REGISTRATION_ENABLED itself.
            return self.process_zoom_import(request, obj.pk)
        return super().response_change(request, obj)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        """Expose flags + JS-needed data to the change-form template."""
        extra_context = extra_context or {}
        extra_context["zoom_registration_enabled"] = settings.ZOOM_REGISTRATION_ENABLED
        # IDs the inline JS uses to live-toggle the evaluates field row.
        extra_context["evaluator_role_ids"] = list(
            Role.objects.filter(is_evaluator_role=True).values_list("id", flat=True)
        )
        # IDs the inline JS uses to live-toggle the Pathways fields.
        extra_context["pathways_role_ids"] = list(
            Role.objects.filter(shows_pathways_fields=True).values_list("id", flat=True)
        )
        return super().change_view(
            request, object_id, form_url=form_url, extra_context=extra_context
        )


@admin.register(MeetingRole)
class MeetingRoleAdmin(admin.ModelAdmin):
    list_display = ("meeting", "role", "user", "in_person", "evaluates", "sort_order")
    list_filter = (
        "meeting",
        "role",
        "in_person",
        "role__is_evaluator_role",
        "role__is_evaluated_role",
    )
    list_editable = ("user", "sort_order")
    # The evaluates picker would list every MeetingRole otherwise; raw_id_fields
    # gives a popup search instead. Editing in the Meeting-scoped inline is
    # the primary workflow; this is just to keep the standalone admin sane.
    raw_id_fields = ("evaluates",)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("meeting", "who_attended", "guest_email", "timestamp")
    list_filter = ("meeting", ("user", admin.EmptyFieldListFilter))
    search_fields = ("guest_first_name", "guest_last_name", "guest_email")
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
        return f"{obj.guest_first_name} {obj.guest_last_name} (Walk-in)"
