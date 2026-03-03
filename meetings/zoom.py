import re
import time

import requests
from django.conf import settings

from members.models import User
from .models import Attendance

# Module-level token cache
_token_cache = {"token": None, "expires_at": 0}


def extract_zoom_meeting_id(url):
    """Extract the numeric meeting ID from a Zoom URL."""
    match = re.search(r"/j/(\d+)", url)
    if match:
        return match.group(1)
    return None


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
    response.raise_for_status()
    data = response.json()

    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 60

    return _token_cache["token"]


def fetch_zoom_registrants(meeting_id):
    """Fetch all approved registrants for a Zoom meeting, handling pagination."""
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
        response.raise_for_status()
        data = response.json()

        registrants.extend(data.get("registrants", []))

        next_page_token = data.get("next_page_token", "")
        if not next_page_token:
            break

    return registrants


def import_zoom_registrants(meeting):
    """Import Zoom registrants as Attendance records for a meeting.

    Returns (members_count, guests_count, skipped_count).
    """
    meeting_id = extract_zoom_meeting_id(meeting.zoom_link)
    if not meeting_id:
        raise ValueError("Could not extract Zoom meeting ID from the zoom_link.")

    registrants = fetch_zoom_registrants(meeting_id)

    # Build a lookup of existing member emails
    users_by_email = {u.email.lower(): u for u in User.objects.filter(is_active=True) if u.email}

    # Build a set of existing attendance for this meeting
    existing_user_ids = set(
        meeting.attendances.filter(user__isnull=False).values_list("user_id", flat=True)
    )
    existing_guest_emails = set(
        meeting.attendances.filter(user__isnull=True)
        .exclude(guest_email="")
        .values_list("guest_email", flat=True)
    )

    members_count = 0
    guests_count = 0
    skipped_count = 0

    for reg in registrants:
        email = reg.get("email", "").lower().strip()
        if not email:
            skipped_count += 1
            continue

        user = users_by_email.get(email)

        if user:
            if user.id in existing_user_ids:
                skipped_count += 1
                continue
            Attendance.objects.create(meeting=meeting, user=user)
            existing_user_ids.add(user.id)
            members_count += 1
        else:
            if email in existing_guest_emails:
                skipped_count += 1
                continue
            Attendance.objects.create(
                meeting=meeting,
                guest_first_name=reg.get("first_name", ""),
                guest_last_name=reg.get("last_name", ""),
                guest_email=email,
            )
            existing_guest_emails.add(email)
            guests_count += 1

    return members_count, guests_count, skipped_count
