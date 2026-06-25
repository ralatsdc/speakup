from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from meetings.models import Meeting


def landing_page(request):
    """Public landing page with about info and upcoming meeting dates."""
    # Keep a meeting listed through the whole day it occurs; drop it the next
    # day. Comparing the calendar date (not the datetime) avoids hiding a
    # meeting once its start time has passed earlier that same day.
    meetings = (
        Meeting.objects.filter(date__date__gte=timezone.localdate())
        .order_by("date")[:10]
    )
    return render(request, "core/landing.html", {"meetings": meetings})


@login_required
def help_page(request):
    template = "core/help_admin.html" if request.user.is_staff else "core/help_user.html"
    return render(request, template)
