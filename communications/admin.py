from urllib.parse import urlencode

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone

from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("subject", "audience", "created_at", "sent_at")
    readonly_fields = ("sent_at",)
    actions = ["send_announcement"]
    change_form_template = "communications/admin/announcement_change_form.html"

    @admin.action(description="Send selected announcements via Email")
    def send_announcement(self, request, queryset):
        for announcement in queryset:
            count = announcement.send()
            announcement.sent_at = timezone.now()
            announcement.save()
            self.message_user(
                request,
                f"Sent '{announcement.subject}' to {count} recipients.",
                messages.SUCCESS,
            )

    def response_change(self, request, obj):
        """The 'Send Announcement' button routes to the review-before-send page
        instead of dispatching immediately."""
        if "_send-announcement" in request.POST:
            url = reverse("email_review") + "?" + urlencode(
                {"workflow": "announcement", "announcement": obj.id})
            return HttpResponseRedirect(url)
        return super().response_change(request, obj)
