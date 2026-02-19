from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from meetings.models import Meeting


def landing_page(request):
    """Public landing page with about info and upcoming meeting dates."""
    meetings = Meeting.objects.filter(date__gte=timezone.now()).order_by("date")[:10]
    return render(request, "core/landing.html", {"meetings": meetings})


@login_required
def help_page(request):
    template = "core/help_admin.html" if request.user.is_staff else "core/help_user.html"
    return render(request, template)
