from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Meeting, MeetingRole


def upcoming_meetings(request):

    # 1. Get current time to filter out old meetings
    now = timezone.now()

    # 2. Query with optimization
    # prefetch_related is crucial here: it grabs the Roles and the Users
    # associated with those roles in the same DB transaction.
    meetings = (
        Meeting.objects.filter(date__gte=now)
        .order_by("date")
        .prefetch_related(
            "roles",  # The pivot table
            "roles__role",  # The role definition (e.g., "Timer")
            "roles__user",  # The assigned user
        )
    )

    return render(request, "meetings/upcoming.html", {"meetings": meetings})


@login_required
@require_POST
def toggle_role(request, role_id):
    """
    Handles the HTMX request to claim or drop a role.
    Returns ONLY the HTML for the specific table row.
    """
    assignment = get_object_or_404(MeetingRole, id=role_id)

    # Logic:
    # 1. If I am already assigned, I am clicking to DROP it.
    if assignment.user == request.user:
        assignment.user = None
        assignment.save()

    # 2. If nobody is assigned, I am clicking to CLAIM it.
    elif assignment.user is None:
        assignment.user = request.user
        assignment.save()

    # 3. If someone else is assigned, do nothing (security check)
    else:
        return HttpResponseForbidden("This role is already taken.")

    # Return the partial HTML snippet for just this row
    return render(
        request, "meetings/partials/role_row.html", {"assignment": assignment}
    )
