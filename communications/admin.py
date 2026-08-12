from urllib.parse import urlencode

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from .forms import AnnouncementAdminForm
from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    form = AnnouncementAdminForm
    list_display = ("subject", "audience", "recipient_summary", "created_at", "sent_at")
    readonly_fields = ("sent_at",)
    # A dual list box rather than autocomplete: at club size the useful action
    # is scanning the roster and ticking people off, not recalling exact names.
    filter_horizontal = ("recipients",)
    actions = ["send_announcement"]
    change_form_template = "communications/admin/announcement_change_form.html"

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

    @admin.action(description="Send selected announcements via Email")
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

    def response_change(self, request, obj):
        """The 'Send Announcement' button routes to the review-before-send page
        instead of dispatching immediately."""
        if "_send-announcement" in request.POST:
            url = reverse("email_review") + "?" + urlencode(
                {"workflow": "announcement", "announcement": obj.id})
            return HttpResponseRedirect(url)
        return super().response_change(request, obj)
