import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Meeting, MeetingRole, Attendance

User = get_user_model()


@login_required
def upcoming_meetings(request):
    """Homepage: shows upcoming meetings with their role assignments."""
    now = timezone.now()
    meetings_qs = (
        Meeting.objects.filter(date__gte=now)
        .order_by("date")
        .prefetch_related("roles", "roles__role", "roles__user")
    )

    paginator = Paginator(meetings_qs, 10)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "meetings/upcoming.html", {"meetings": page})


@login_required
@require_POST
def toggle_role(request, role_id):
    """HTMX endpoint: claim or drop a meeting role. Returns the updated table row partial."""
    assignment = get_object_or_404(MeetingRole, id=role_id)

    if assignment.user == request.user:
        # Drop: user is un-signing from their own role
        assignment.user = None
        assignment.save()

    elif assignment.user is None:
        # Claim: enforce one-role-per-meeting limit (officers/superusers exempt)
        has_existing_role = MeetingRole.objects.filter(
            meeting=assignment.meeting, user=request.user
        ).exists()
        can_bypass = request.user.is_officer or request.user.is_superuser

        if has_existing_role and not can_bypass:
            response = render(
                request, "meetings/partials/role_row.html", {"assignment": assignment}
            )
            response["HX-Trigger"] = json.dumps(
                {
                    "showAlert": "You have already signed up for a role for this meeting. Please drop your current role first."
                }
            )
            return response

        assignment.user = request.user
        assignment.save()

    else:
        # Already taken by someone else
        return HttpResponseForbidden("This role is already taken.")

    return render(
        request, "meetings/partials/role_row.html", {"assignment": assignment}
    )


@login_required
@require_POST
def save_role_note(request, role_id):
    """HTMX endpoint: update the notes on a role assignment (officer or assignee only)."""
    assignment = get_object_or_404(MeetingRole, id=role_id)

    can_edit = request.user.is_officer or (assignment.user == request.user)
    if not can_edit:
        return HttpResponseForbidden("You do not have permission to edit this note.")

    assignment.notes = request.POST.get("note_content", "").strip()
    assignment.save()

    return render(
        request, "meetings/partials/role_row.html", {"assignment": assignment}
    )


@login_required
def checkin_kiosk(request):
    """Displays the check-in grid for today's meeting (or the next upcoming one)."""
    today = timezone.now().date()
    meeting = Meeting.objects.filter(date__date=today).first()

    if not meeting:
        meeting = Meeting.objects.filter(date__gte=today).order_by("date").first()

    context = {"meeting": meeting}

    if meeting:
        members = User.objects.filter(is_active=True).order_by("first_name")
        checked_in_ids = set(meeting.attendances.values_list("user_id", flat=True))
        context.update({"members": members, "checked_in_ids": checked_in_ids})

    return render(request, "meetings/kiosk.html", context)


@login_required
@require_POST
def checkin_member(request, meeting_id, user_id):
    """HTMX endpoint: toggle attendance for a member (check in / undo)."""
    meeting = get_object_or_404(Meeting, id=meeting_id)
    user = get_object_or_404(User, id=user_id)

    attendance = Attendance.objects.filter(meeting=meeting, user=user).first()

    is_present = False
    if attendance:
        attendance.delete()
    else:
        Attendance.objects.create(meeting=meeting, user=user)
        is_present = True

    return render(
        request,
        "meetings/partials/checkin_button.html",
        {"meeting": meeting, "member": user, "is_present": is_present},
    )


def checkin_guest(request, meeting_id):
    """POST endpoint: record a walk-in guest's name and email."""
    if request.method == "POST":
        meeting = get_object_or_404(Meeting, id=meeting_id)
        name = request.POST.get("guest_name")
        email = request.POST.get("guest_email")

        if name and email:
            Attendance.objects.create(
                meeting=meeting, guest_name=name, guest_email=email
            )
            return render(
                request, "meetings/partials/guest_success.html", {"name": name}
            )

    return HttpResponseForbidden()
