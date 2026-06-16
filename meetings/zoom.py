import re
import time
from datetime import timedelta
from urllib.parse import quote

import requests
from django.conf import settings
from django.utils import timezone as tz

from members.models import User
from .models import Attendance

# Module-level token cache
_token_cache = {"token": None, "expires_at": 0}


def _raise_for_zoom(response):
    """Like ``response.raise_for_status()`` but folds Zoom's JSON error body
    (``{"code", "message"}``) into the exception text, so failures surface the
    actual reason instead of a bare status line. Preserves ``HTTPError`` (with
    ``.response``) so callers can still branch on the status code."""
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = ""
        try:
            detail = response.json().get("message", "")
        except ValueError:
            detail = (response.text or "")[:200]
        if detail:
            raise requests.HTTPError(f"{exc} — {detail}", response=response) from exc
        raise


def extract_zoom_meeting_id(url):
    """Extract the numeric meeting ID from a Zoom join URL (.../j/<id>)."""
    match = re.search(r"/j/(\d+)", url)
    if match:
        return match.group(1)
    return None


def resolve_meeting_id(meeting):
    """The numeric Zoom meeting ID to use for API calls. Prefers the meeting's
    own ``zoom_meeting_id`` (paired with its zoom_link), then the meeting
    type's default, then a /j/ join link if one happens to be set. The stored
    zoom_link is a registration URL with no numeric ID, so it can't supply one.
    Returns None if nothing is available."""
    own = (meeting.zoom_meeting_id or "").replace(" ", "")
    if own:
        return own
    meeting_type = meeting.meeting_type
    configured = (getattr(meeting_type, "zoom_meeting_id", "") or "").replace(" ", "")
    if configured:
        return configured
    return extract_zoom_meeting_id(meeting.zoom_link or "")


def get_zoom_access_token():
    """Get a Zoom Server-to-Server OAuth access token, using a cached value if valid."""
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]

    response = requests.post(
        "https://zoom.us/oauth/token",
        params={"grant_type": "account_credentials", "account_id": settings.ZOOM_ACCOUNT_ID},
        auth=(settings.ZOOM_CLIENT_ID, settings.ZOOM_CLIENT_SECRET),
        timeout=10,
    )
    _raise_for_zoom(response)
    data = response.json()

    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60

    return _token_cache["token"]


def _parse_zoom_datetime(dt_string):
    """Parse a Zoom API datetime string (ISO 8601) into an aware datetime."""
    from django.utils.dateparse import parse_datetime

    dt = parse_datetime(dt_string or "")
    if dt and tz.is_naive(dt):
        dt = tz.make_aware(dt, tz.utc)
    return dt


def fetch_zoom_registrants(meeting_id):
    """Fetch all approved registrants for a Zoom meeting, handling pagination.

    Used to answer "has this person already registered?" when nudging remote
    role-takers — not for attendance (see ``import_zoom_participants``)."""
    token = get_zoom_access_token()
    registrants = []
    next_page_token = ""

    while True:
        params = {"status": "approved", "page_size": 300}
        if next_page_token:
            params["next_page_token"] = next_page_token

        response = requests.get(
            f"https://api.zoom.us/v2/meetings/{meeting_id}/registrants",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=10,
        )
        _raise_for_zoom(response)
        data = response.json()

        registrants.extend(data.get("registrants", []))

        next_page_token = data.get("next_page_token", "")
        if not next_page_token:
            break

    return registrants


# --- participant-attendance import -----------------------------------------


def fetch_past_meeting_instances(meeting_id):
    """Return the list of past occurrences ``[{uuid, start_time}, ...]`` for a
    (recurring) meeting ID."""
    token = get_zoom_access_token()
    response = requests.get(
        f"https://api.zoom.us/v2/past_meetings/{meeting_id}/instances",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    _raise_for_zoom(response)
    return response.json().get("meetings", [])


def select_occurrence_uuid(instances, meeting_date):
    """Pick the past occurrence whose start_time is closest to ``meeting_date``,
    within a one-day window. Returns its UUID, or None if there's no match."""
    best_uuid = None
    best_delta = None
    for inst in instances:
        start = _parse_zoom_datetime(inst.get("start_time"))
        uuid = inst.get("uuid")
        if not start or not uuid:
            continue
        delta = abs(start - meeting_date)
        if delta <= timedelta(days=1) and (best_delta is None or delta < best_delta):
            best_uuid, best_delta = uuid, delta
    return best_uuid


def _encode_uuid(uuid):
    """Zoom requires double URL-encoding of meeting UUIDs containing '/'."""
    if "/" in uuid:
        return quote(quote(uuid, safe=""), safe="")
    return uuid


def _normalize_participant(p):
    return {
        "name": (p.get("name") or "").strip(),
        "email": (p.get("user_email") or "").strip(),
        "join_time": p.get("join_time", ""),
    }


def _paginate_participants(url, token):
    participants = []
    next_page_token = ""
    while True:
        params = {"page_size": 300}
        if next_page_token:
            params["next_page_token"] = next_page_token
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=10,
        )
        _raise_for_zoom(response)
        data = response.json()
        participants.extend(data.get("participants", []))
        next_page_token = data.get("next_page_token", "")
        if not next_page_token:
            break
    return [_normalize_participant(p) for p in participants]


def fetch_zoom_participants(meeting_uuid):
    """Fetch participants for one past meeting occurrence, handling pagination.

    Tries the report endpoint first (most reliable emails); on an HTTP 4xx
    (e.g. the plan/scope isn't available) falls back to the past_meetings
    endpoint. Returns normalized ``{name, email, join_time}`` dicts."""
    token = get_zoom_access_token()
    encoded = _encode_uuid(meeting_uuid)
    endpoints = (
        f"https://api.zoom.us/v2/report/meetings/{encoded}/participants",
        f"https://api.zoom.us/v2/past_meetings/{encoded}/participants",
    )
    for i, url in enumerate(endpoints):
        try:
            return _paginate_participants(url, token)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            is_last = i == len(endpoints) - 1
            if status is not None and 400 <= status < 500 and not is_last:
                continue  # try the fallback endpoint
            raise
    return []


def _split_name(name):
    """Split a Zoom display name into (first, last)."""
    parts = name.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def import_zoom_participants(meeting):
    """Import the participants who actually joined the meeting's Zoom call as
    Attendance records.

    Matches each participant to an active member by email, then by a unique
    display-name match; unmatched joiners become guest Attendance rows.

    Returns (members_count, guests_count, skipped_count).
    """
    meeting_id = resolve_meeting_id(meeting)
    if not meeting_id:
        raise ValueError(
            "No Zoom meeting ID — set the meeting type's Zoom meeting ID."
        )

    instances = fetch_past_meeting_instances(meeting_id)
    occurrence_uuid = select_occurrence_uuid(instances, meeting.date)
    if not occurrence_uuid:
        raise ValueError("No Zoom occurrence found for this meeting's date.")

    participants = fetch_zoom_participants(occurrence_uuid)

    # Dedup rejoins: collapse by lowercased email, else by normalized name.
    unique = {}
    for p in participants:
        key = p["email"].lower() if p["email"] else f"name:{p['name'].lower()}"
        if key == "name:":
            continue  # no email and no name — nothing to record
        unique.setdefault(key, p)
    participants = list(unique.values())

    # Member lookup tables over active users.
    active = list(User.objects.filter(is_active=True))
    users_by_email = {u.email.lower(): u for u in active if u.email}
    name_to_user = {}
    name_counts = {}
    for u in active:
        nk = (u.first_name.strip().lower(), u.last_name.strip().lower())
        if not nk[0] and not nk[1]:
            continue
        name_counts[nk] = name_counts.get(nk, 0) + 1
        name_to_user[nk] = u
    # Only keep names that map to exactly one member (avoid false matches).
    users_by_name = {k: v for k, v in name_to_user.items() if name_counts[k] == 1}

    # Existing attendance for this meeting, for dedup.
    existing_user_ids = set(
        meeting.attendances.filter(user__isnull=False).values_list("user_id", flat=True)
    )
    existing_guest_emails = {
        e.lower()
        for e in meeting.attendances.filter(user__isnull=True)
        .exclude(guest_email="")
        .values_list("guest_email", flat=True)
    }
    existing_guest_names = {
        (fn.strip().lower(), ln.strip().lower())
        for fn, ln in meeting.attendances.filter(user__isnull=True).values_list(
            "guest_first_name", "guest_last_name"
        )
    }

    members_count = guests_count = skipped_count = 0

    for p in participants:
        email = p["email"].lower()
        first, last = _split_name(p["name"])

        user = users_by_email.get(email) if email else None
        if user is None and (first or last):
            user = users_by_name.get((first.lower(), last.lower()))

        if user:
            if user.id in existing_user_ids:
                skipped_count += 1
                continue
            Attendance.objects.create(meeting=meeting, user=user)
            existing_user_ids.add(user.id)
            members_count += 1
        else:
            name_key = (first.lower(), last.lower())
            already = (email and email in existing_guest_emails) or (
                not email and name_key in existing_guest_names
            )
            if already:
                skipped_count += 1
                continue
            Attendance.objects.create(
                meeting=meeting,
                guest_first_name=first,
                guest_last_name=last,
                guest_email=p["email"],
            )
            if email:
                existing_guest_emails.add(email)
            existing_guest_names.add(name_key)
            guests_count += 1

    return members_count, guests_count, skipped_count
