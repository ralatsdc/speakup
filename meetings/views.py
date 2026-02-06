from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Meeting, MeetingRole, Attendance


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


User = get_user_model()


@login_required
def checkin_kiosk(request):
    # 1. Find the meeting happening today (or the closest upcoming one for testing)
    today = timezone.now().date()
    meeting = Meeting.objects.filter(date__date=today).first()

    # Fallback: if testing and no meeting today, get the next one
    if not meeting:
        meeting = Meeting.objects.filter(date__gte=today).order_by("date").first()

    context = {"meeting": meeting}

    if meeting:
        # Get all active members to display on the grid
        members = User.objects.filter(is_active=True).order_by("first_name")

        # Get IDs of people who already checked in
        checked_in_ids = set(meeting.attendances.values_list("user_id", flat=True))

        context.update({"members": members, "checked_in_ids": checked_in_ids})

    return render(request, "meetings/kiosk.html", context)


@login_required
@require_POST
def checkin_member(request, meeting_id, user_id):
    """
    HTMX: Toggles attendance for a member.
    """
    meeting = get_object_or_404(Meeting, id=meeting_id)
    user = get_object_or_404(User, id=user_id)

    # Check if exists
    attendance = Attendance.objects.filter(meeting=meeting, user=user).first()

    is_present = False
    if attendance:
        # If clicked again, remove check-in (Undo)
        attendance.delete()
    else:
        # Create check-in
        Attendance.objects.create(meeting=meeting, user=user)
        is_present = True

    return render(
        request,
        "meetings/partials/checkin_button.html",
        {"meeting": meeting, "member": user, "is_present": is_present},
    )


def checkin_guest(request, meeting_id):
    """
    Standard POST: Handles guest form submission.
    """
    if request.method == "POST":
        meeting = get_object_or_404(Meeting, id=meeting_id)
        name = request.POST.get("guest_name")
        email = request.POST.get("guest_email")

        if name and email:
            Attendance.objects.create(
                meeting=meeting, guest_name=name, guest_email=email
            )

            # Use HTMX to show a "Success" message without reloading
            return render(
                request, "meetings/partials/guest_success.html", {"name": name}
            )

    return HttpResponseForbidden()
