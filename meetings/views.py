import base64
import io
import json
from pathlib import Path

import qrcode
import qrcode.constants
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

AGENDA_TEMPLATE = (
    Path(__file__).parent / "templates" / "meetings" / "agenda" / "agenda_template.docx"
)

from .models import Meeting, MeetingRole, Attendance

User = get_user_model()


def _generate_qr_data_uri(url):
    """Generate a QR code as a base64-encoded PNG data URI."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _build_agenda_sections(meeting):
    """Build an ordered list of agenda sections from the meeting's sessions.

    Returns a list of dicts:
        {"session": Session, "note": str, "roles": [MeetingRole, ...]}
    Sessions with takes_roles=False will have an empty roles list.
    Roles not assigned to any session are grouped in a final None section.
    """
    roles = list(
        meeting.roles.select_related("role", "user", "session").order_by(
            "sort_order", "id"
        )
    )

    meeting_sessions = meeting.meeting_sessions.select_related("session").order_by(
        "sort_order"
    )

    if not meeting_sessions:
        return [{"session": None, "note": "", "roles": roles}]

    sections = []
    used_role_ids = set()
    for ms in meeting_sessions:
        session = ms.session
        if session.takes_roles:
            session_roles = [r for r in roles if r.session_id == session.id]
            used_role_ids.update(r.id for r in session_roles)
        else:
            session_roles = []
        sections.append({"session": session, "note": ms.note, "roles": session_roles})

    # Roles not assigned to any session
    unassigned = [r for r in roles if r.id not in used_role_ids]
    if unassigned:
        sections.append({"session": None, "note": "", "roles": unassigned})

    return sections


def meeting_agenda(request, meeting_id):
    """Public page: presentable meeting agenda with roles and notes."""
    meeting = get_object_or_404(Meeting, id=meeting_id)
    sections = _build_agenda_sections(meeting)
    return render(
        request, "meetings/agenda.html", {"meeting": meeting, "sections": sections}
    )


def _replace_in_paragraph(paragraph, placeholder, replacement):
    """Replace placeholder text in a paragraph, handling Word's run-splitting."""
    full_text = "".join(run.text for run in paragraph.runs)
    if placeholder not in full_text:
        return False
    new_text = full_text.replace(placeholder, replacement)
    # Put all text in the first run (preserves its formatting), clear the rest
    for i, run in enumerate(paragraph.runs):
        run.text = new_text if i == 0 else ""
    return True


def _remove_paragraph(paragraph):
    """Remove a paragraph element from the document XML."""
    p = paragraph._element
    p.getparent().remove(p)


def meeting_agenda_download(request, meeting_id):
    """Public endpoint: download the meeting agenda as a Word document."""
    meeting = get_object_or_404(Meeting, id=meeting_id)

    doc = Document(AGENDA_TEMPLATE)

    # Required placeholders — always replaced
    replacements = {
        "{{DATE}}": meeting.date.strftime("%A, %B %d, %Y"),
        "{{TIME}}": meeting.date.strftime("%I:%M %p"),
    }

    # Optional placeholders — entire paragraph removed when empty
    optional = {
        "{{THEME}}": meeting.theme,
        "{{WORD_OF_THE_DAY}}": meeting.word_of_the_day,
        "{{ZOOM_LINK}}": meeting.zoom_link,
    }

    paragraphs_to_remove = []
    for paragraph in doc.paragraphs:
        for placeholder, value in replacements.items():
            _replace_in_paragraph(paragraph, placeholder, value)

        for placeholder, value in optional.items():
            full_text = "".join(run.text for run in paragraph.runs)
            if placeholder in full_text:
                if value:
                    _replace_in_paragraph(paragraph, placeholder, value)
                else:
                    paragraphs_to_remove.append(paragraph)

    for p in paragraphs_to_remove:
        _remove_paragraph(p)

    # Populate the 2-column table (session | roles)
    sections = _build_agenda_sections(meeting)
    table = doc.tables[0]

    first = True
    for section in sections:
        session = section["session"]
        if first:
            row_cells = table.rows[0].cells
            first = False
        else:
            row_cells = table.add_row().cells

        # Cell 0: session name, duration, and notes
        c = row_cells[0]
        p1 = c.paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p1.paragraph_format.space_before = Pt(6)
        if session:
            r = p1.add_run(session.name)
            if session.duration_minutes or section["note"]:
                p2 = c.add_paragraph()
                p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                p2.paragraph_format.space_after = Pt(6)
            if session.duration_minutes:
                p2.add_run(f"{session.duration_minutes} min")
            if section["note"]:
                p2.add_run(section["note"])
        else:
            r = p1.add_run("Other")
        r.bold = True

        # Cell 1: two paragraphs per role (name: member, then [L]/[R] time - note)
        c = row_cells[1]
        if section["roles"]:
            first = True
            for assignment in section["roles"]:
                # Role + member paragraph
                if first:
                    p = c.paragraphs[0]
                    p.paragraph_format.space_before = Pt(6)
                    first = False
                else:
                    p = c.add_paragraph()
                member = (
                    f"{assignment.user.first_name} {assignment.user.last_name}"
                    if assignment.user
                    else "(Open)"
                )
                r = p.add_run(f"{assignment.role.name}:")
                r.bold = True
                p.add_run(f"{member}")

                # Detail paragraph: [L]/[R], time in minutes, note
                p = c.add_paragraph()
                p.add_run("[L]" if assignment.in_person else "[R]")
                if assignment.time_minutes:
                    p.add_run(f"{assignment.time_minutes} min")
                if assignment.notes:
                    p.add_run(assignment.notes)
            p.paragraph_format.space_after = Pt(6)
        elif session and not session.takes_roles:
            p = c.paragraphs[0]
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            p.add_run("Break")

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    filename = f"agenda-{meeting.date.strftime('%Y-%m-%d')}.docx"
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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
        # Claim: enforce one-role-per-meeting limit
        # (officers/superusers exempt), and no guest sign ups
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

        if request.user.is_guest:
            response = render(
                request, "meetings/partials/role_row.html", {"assignment": assignment}
            )
            response["HX-Trigger"] = json.dumps(
                {"showAlert": "Guests cannot sign up for a role. Become a member!"}
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

        kiosk_url = f"{settings.SITE_URL}{reverse('checkin_kiosk')}"
        qr_data_uri = _generate_qr_data_uri(kiosk_url)
        agenda_url = reverse("meeting_agenda", args=[meeting.id])

        context.update(
            {
                "members": members,
                "checked_in_ids": checked_in_ids,
                "qr_data_uri": qr_data_uri,
                "agenda_url": agenda_url,
            }
        )

    return render(request, "meetings/kiosk.html", context)


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
