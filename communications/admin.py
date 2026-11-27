from urllib.parse import urlencode

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html

from .forms import AnnouncementAdminForm, EmailTemplateAdminForm
from .models import Announcement, EmailTemplate, Sender


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    form = AnnouncementAdminForm
    list_display = ("subject", "audience", "recipient_summary", "created_at", "sent_at")
    fields = ("template", "subject", "body", "audience", "recipients", "sent_at")
    readonly_fields = ("sent_at",)
    # A dual list box rather than autocomplete: at club size the useful action
    # is scanning the roster and ticking people off, not recalling exact names.
    filter_horizontal = ("recipients",)
    actions = ["send_announcement", "save_as_template"]
    change_form_template = "communications/admin/announcement_change_form.html"

    def get_fields(self, request, obj=None):
        """Leave the template picker off the view-only page: there is nothing
        to fill in, and admin can't render a non-model field as read-only."""
        fields = super().get_fields(request, obj)
        if obj is not None and not self.has_change_permission(request, obj):
            return [f for f in fields if f != "template"]
        return fields

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Only offer active members, so nobody addresses an announcement to
        someone who has left the club."""
        if db_field.name == "recipients":
            kwargs["queryset"] = (
                db_field.remote_field.model.objects.filter(is_active=True)
                .exclude(username="admin")
                .order_by("first_name", "last_name")
            )
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    @admin.display(description="Recipients")
    def recipient_summary(self, obj):
        """Names for a hand-picked announcement; the audience covers the rest."""
        if obj.audience != Announcement.AUDIENCE_SELECTED:
            return "—"
        names = [str(u) for u in obj.recipients.all()[:4]]
        extra = obj.recipients.count() - len(names)
        return ", ".join(names) + (f" +{extra} more" if extra > 0 else "")

    @admin.action(description="Review & send selected announcements…")
    def send_announcement(self, request, queryset):
        """Route to the review-before-send page rather than dispatching here.

        This action used to mail immediately from the changelist — the one
        send path with no preview of who it was going to, which matters most
        for a hand-picked audience.
        """
        ids = list(queryset.order_by("created_at").values_list("id", flat=True))
        if not ids:
            self.message_user(request, "No announcements selected.", messages.WARNING)
            return None
        url = reverse("email_review") + "?" + urlencode(
            [("workflow", "announcement")] + [("announcement", i) for i in ids])
        return HttpResponseRedirect(url)

    def has_add_template_permission(self, request):
        return request.user.has_perm("communications.add_emailtemplate")

    @admin.action(description="Save selected announcements as templates",
                  permissions=["add_template"])
    def save_as_template(self, request, queryset):
        for announcement in queryset.order_by("created_at"):
            template = EmailTemplate.create_from(announcement)
            url = reverse("admin:communications_emailtemplate_change",
                          args=[template.pk])
            self.message_user(
                request,
                format_html('Saved template “<a href="{}">{}</a>”.',
                            url, template.name),
                messages.SUCCESS)

    def _review_redirect(self, request, obj):
        """The 'Save & review to send' button routes to the review-before-send
        page instead of dispatching immediately. None if it wasn't pressed."""
        if "_send-announcement" in request.POST:
            url = reverse("email_review") + "?" + urlencode(
                {"workflow": "announcement", "announcement": obj.id})
            return HttpResponseRedirect(url)
        return None

    def response_add(self, request, obj, post_url_continue=None):
        # The button is on the add form too; without this it saved and fell
        # back to the changelist like a plain Save.
        return self._review_redirect(request, obj) or super().response_add(
            request, obj, post_url_continue)

    def response_change(self, request, obj):
        return self._review_redirect(request, obj) or super().response_change(
            request, obj)


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    form = EmailTemplateAdminForm
    list_display = ("name", "subject")
    search_fields = ("name", "subject", "body")


@admin.register(Sender)
class SenderAdmin(admin.ModelAdmin):
    """Extra “Send from” choices for the review-before-send page. The default
    sender (``DEFAULT_FROM_EMAIL``) is always offered and isn't listed here."""

    list_display = ("email", "name", "is_active")
    list_filter = ("is_active",)
