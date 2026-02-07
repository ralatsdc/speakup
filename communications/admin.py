from django.contrib import admin
from django.utils import timezone
from django.contrib import messages
from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("subject", "audience", "created_at", "sent_at")
    readonly_fields = ("sent_at",)
    actions = ["send_announcement"]

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
