"""Officer-facing member-activity report.

Renders two custom admin views, wired into ``CustomUserAdmin.get_urls()``:

* Summary — every active non-guest member with their meetings-attended count
  and total roles-taken count over an optional date range.
* Detail — one member's per-meeting history (date, role taken or "attended
  only", attendance mode) plus a per-role count breakdown.

Both views are gated by ``admin_site.admin_view()`` (is_staff). Officers get
``is_staff`` via the ``members.signals`` post_save handler, so the existing
officer/superuser audience already has access — no extra permission flags.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from meetings.models import Attendance, Meeting, MeetingRole, Role
from meetings.utils import send_role_invite

from .models import User


def _range_presets(today):
    """Pre-computed (start, end) ranges for the report's quick-filter buttons.

    Bi-weekly meetings make per-day shortcuts noisy; longer rolling windows
    match how officers actually look at activity (mentor pairings, role
    rotation, year-end reviews).
    """
    return [
        {
            "label": "Last month",
            "start": (today - timedelta(days=30)).isoformat(),
            "end": today.isoformat(),
        },
        {
            "label": "Last 3 months",
            "start": (today - timedelta(days=90)).isoformat(),
            "end": today.isoformat(),
        },
        {
            "label": "Last year",
            "start": (today - timedelta(days=365)).isoformat(),
            "end": today.isoformat(),
        },
    ]


def _parse_date(value):
    """Parse an ISO ``YYYY-MM-DD`` string from a query param. Returns None on
    empty/invalid input rather than raising — the report should degrade to
    "all time" if a user fat-fingers the URL."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _aware_range_bounds(start_date, end_date):
    """Convert inclusive ``start_date``/``end_date`` into timezone-aware
    datetimes so they can be compared against ``Meeting.date`` (a
    DateTimeField). ``end`` is the next day's 00:00 so the whole end-of-range
    day is included.
    """
    tz = timezone.get_current_timezone()
    start_dt = (
        timezone.make_aware(datetime.combine(start_date, time.min), tz)
        if start_date
        else None
    )
    end_dt = (
        timezone.make_aware(
            datetime.combine(date.fromordinal(end_date.toordinal() + 1), time.min), tz
        )
        if end_date
        else None
    )
    return start_dt, end_dt


@staff_member_required
def activity_report(request):
    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))
    start_dt, end_dt = _aware_range_bounds(start, end)

    attendance_filter = Q()
    role_filter = Q()
    if start_dt:
        attendance_filter &= Q(attendance__meeting__date__gte=start_dt)
        role_filter &= Q(meeting_roles__meeting__date__gte=start_dt)
    if end_dt:
        attendance_filter &= Q(attendance__meeting__date__lt=end_dt)
        role_filter &= Q(meeting_roles__meeting__date__lt=end_dt)

    members = (
        User.objects.filter(is_active=True, is_guest=False)
        .annotate(
            meetings_attended=Count("attendance", filter=attendance_filter, distinct=True),
            roles_taken=Count("meeting_roles", filter=role_filter, distinct=True),
        )
        .order_by("first_name", "last_name", "username")
    )

    # Optional "has / has not taken <role>" filter, honoring the date range.
    # Drives the officer workflow: find who's never done a role, then invite.
    role_id = request.GET.get("role") or ""
    taken = request.GET.get("taken") or ""  # "yes" | "no" | ""
    selected_role = None
    if role_id and taken in ("yes", "no"):
        selected_role = Role.objects.filter(pk=role_id, show_on_agenda=True).first()
    if selected_role:
        took = MeetingRole.objects.filter(role=selected_role, user__isnull=False)
        if start_dt:
            took = took.filter(meeting__date__gte=start_dt)
        if end_dt:
            took = took.filter(meeting__date__lt=end_dt)
        took_ids = took.values_list("user_id", flat=True).distinct()
        members = (members.filter(id__in=took_ids) if taken == "yes"
                   else members.exclude(id__in=took_ids))

    context = {
        **admin.site.each_context(request),
        "title": "Member activity report",
        "members": members,
        "roles": Role.objects.filter(show_on_agenda=True).order_by("name"),
        "selected_role_id": str(selected_role.pk) if selected_role else "",
        "selected_taken": taken if selected_role else "",
        "presets": _range_presets(timezone.localdate()),
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "has_filter": bool(start or end or selected_role),
        "querystring": _querystring(start, end),
    }
    return render(request, "members/admin/activity_report.html", context)


def _querystring(start, end, **extra):
    """Build a ?start=&end=... querystring (omitting blanks) for preserving the
    date range across links/forms."""
    params = {}
    if start:
        params["start"] = start.isoformat() if hasattr(start, "isoformat") else start
    if end:
        params["end"] = end.isoformat() if hasattr(end, "isoformat") else end
    params.update({k: v for k, v in extra.items() if v})
    return urlencode(params)


@staff_member_required
def activity_report_detail(request, user_id):
    member = get_object_or_404(User, pk=user_id)

    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))
    start_dt, end_dt = _aware_range_bounds(start, end)

    attendance_qs = Attendance.objects.filter(user=member).select_related("meeting")
    role_qs = (
        MeetingRole.objects.filter(user=member)
        .select_related("meeting", "role")
    )
    if start_dt:
        attendance_qs = attendance_qs.filter(meeting__date__gte=start_dt)
        role_qs = role_qs.filter(meeting__date__gte=start_dt)
    if end_dt:
        attendance_qs = attendance_qs.filter(meeting__date__lt=end_dt)
        role_qs = role_qs.filter(meeting__date__lt=end_dt)

    # Build a per-meeting row: roles taken at that meeting, attendance flag.
    by_meeting = defaultdict(lambda: {"meeting": None, "roles": [], "attended": False})
    for att in attendance_qs:
        row = by_meeting[att.meeting_id]
        row["meeting"] = att.meeting
        row["attended"] = True
    for mr in role_qs:
        row = by_meeting[mr.meeting_id]
        row["meeting"] = mr.meeting
        row["roles"].append(mr)

    meeting_rows = sorted(
        by_meeting.values(), key=lambda r: r["meeting"].date, reverse=True
    )

    # Per-role breakdown across EVERY sign-up-able role (not just ones taken),
    # with how many times and when last taken — so officers can spot gaps and
    # invite. Roles never taken show count 0 / last "—".
    taken = {
        row["role"]: row
        for row in role_qs.values("role").annotate(
            count=Count("id"), last_taken=Max("meeting__date")
        )
    }
    role_breakdown = []
    for role in Role.objects.filter(show_on_agenda=True).order_by("name"):
        agg = taken.get(role.id)
        role_breakdown.append({
            "role": role,
            "count": agg["count"] if agg else 0,
            "last_taken": agg["last_taken"] if agg else None,
        })

    # Invites are pointless with no upcoming meeting to sign up for.
    upcoming_exists = Meeting.objects.filter(date__gte=timezone.now()).exists()

    context = {
        **admin.site.each_context(request),
        "title": f"Activity: {member}",
        "member": member,
        "meeting_rows": meeting_rows,
        "role_breakdown": role_breakdown,
        "upcoming_exists": upcoming_exists,
        "total_meetings": sum(1 for r in meeting_rows if r["attended"]),
        "total_roles": role_qs.count(),
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "querystring": _querystring(start, end),
    }
    return render(request, "members/admin/activity_report_detail.html", context)


@require_POST
@staff_member_required
def activity_report_invite(request, user_id, role_id):
    """Email a member inviting them to sign up for a role at an upcoming
    meeting, then return to their detail page with a status message."""
    member = get_object_or_404(User, pk=user_id)
    role = get_object_or_404(Role, pk=role_id, show_on_agenda=True)

    back = reverse("admin:members_user_activity_report_detail", args=[member.pk])
    qs = _querystring(request.POST.get("start"), request.POST.get("end"))
    back = f"{back}?{qs}" if qs else back

    if not Meeting.objects.filter(date__gte=timezone.now()).exists():
        messages.error(request, "No upcoming meetings to invite for.")
        return redirect(back)
    if not member.email:
        messages.error(request, f"{member} has no email address on file.")
        return redirect(back)

    try:
        n = send_role_invite(member, role)
    except Exception:
        messages.error(request, f"Could not send the invite to {member}.")
        return redirect(back)

    if n:
        messages.success(
            request,
            f"Invited {member} to take {role.name} "
            f"({n} upcoming meeting{'s' if n != 1 else ''} with it open).")
    else:
        messages.success(
            request,
            f"Invited {member} to take {role.name} (linked to the sign-up "
            f"page; no upcoming meeting currently has it open).")
    return redirect(back)
