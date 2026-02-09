from django.contrib import admin, messages
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
        """Handle the 'Send Announcement' button on the change form."""
        if "_send-announcement" in request.POST:
            count = obj.send()
            obj.sent_at = timezone.now()
            obj.save()
            self.message_user(
                request,
                f"Sent '{obj.subject}' to {count} recipients.",
                messages.SUCCESS,
            )
            return self.response_post_save_change(request, obj)
        return super().response_change(request, obj)
