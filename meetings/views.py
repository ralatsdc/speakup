import json  # Add this import at the top

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Meeting, MeetingRole, Attendance

User = get_user_model()


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

    # 1. DROP ROLE (Always allowed if it's you)
    # 1. If I am already assigned, I am clicking to DROP it.
    if assignment.user == request.user:
        assignment.user = None
        assignment.save()

    # 2. CLAIM ROLE (Logic update here)
    elif assignment.user is None:

        # A. Check for existing roles in this specific meeting
        has_existing_role = MeetingRole.objects.filter(
            meeting=assignment.meeting, user=request.user
        ).exists()

        # B. Define who can bypass this rule (Officers + Superusers)
        can_bypass = request.user.is_officer or request.user.is_superuser

        # C. Enforce the limit
        if has_existing_role and not can_bypass:
            # Render the row EXACTLY as it is (don't update it)
            response = render(
                request, "meetings/partials/role_row.html", {"assignment": assignment}
            )

            # Send a specific signal to the frontend to show an alert
            response["HX-Trigger"] = json.dumps(
                {
                    "showAlert": "You have already signed up for a role for this meeting. Please drop your current role first."
                }
            )
            return response

        # If pass, save the assignment
        assignment.user = request.user
        assignment.save()

    # 3. If someone else is assigned, do nothing (security check)
    else:
        return HttpResponseForbidden("This role is already taken.")

    # Return the partial HTML snippet for just this row
    return render(
        request, "meetings/partials/role_row.html", {"assignment": assignment}
    )


@login_required
@require_POST
def save_role_note(request, role_id):
    """
    Updates the notes field for a specific role assignment.
    """
    assignment = get_object_or_404(MeetingRole, id=role_id)

    # Permission Check: Only Officers or the Assigned User can edit
    can_edit = request.user.is_officer or (assignment.user == request.user)

    if not can_edit:
        return HttpResponseForbidden("You do not have permission to edit this note.")

    # Update the note
    new_note = request.POST.get("note_content", "").strip()
    assignment.notes = new_note
    assignment.save()

    # Return the updated partial for the row
    return render(
        request, "meetings/partials/role_row.html", {"assignment": assignment}
    )


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
