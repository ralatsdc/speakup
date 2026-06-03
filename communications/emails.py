"""
Shared "review before send" email plumbing.

A *draft* is a uniform structure the review page renders and the send step
dispatches:

    {
      "workflow": "announcement",
      "title": "...",            # heading on the review page
      "back_url": "...",         # Cancel target
      "groups": [
        {
          "key": "all",
          "label": "All active members (89)",
          "subject": "<editable template>",   # may contain {placeholders}
          "body": "<editable template>",
          "placeholders": ["first_name", ...],
          "recipients": [
            {"email": "...", "name": "...", "context": {"first_name": "..."}}
          ],
        },
      ],
    }

Builders produce a draft (no send). ``render_messages`` applies per-group
subject/body overrides (the edits from the review form, falling back to the
draft's own templates) and returns ``send_mass_mail`` tuples; the per-app
``utils`` send functions own the actual ``send_mass_mail`` call (so existing
patch targets keep working). Placeholder substitution is forgiving: an unknown
or fumbled ``{token}`` renders blank rather than raising.
"""

import re

from django.conf import settings

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render(template, context):
    r"""Substitute ``{name}`` tokens from ``context``; missing keys -> ''.
    Stray braces that don't match ``{\w+}`` are left untouched."""
    return _PLACEHOLDER.sub(lambda m: str(context.get(m.group(1), "")), template or "")


def render_messages(groups, edits=None):
    """Turn draft groups into ``send_mass_mail`` tuples, applying ``edits``
    (``{group_key: {"subject": ..., "body": ...}}``) over the defaults."""
    edits = edits or {}
    sender = settings.DEFAULT_FROM_EMAIL
    out = []
    for group in groups:
        override = edits.get(group["key"], {})
        subject_t = override.get("subject") or group["subject"]
        body_t = override.get("body") or group["body"]
        for r in group["recipients"]:
            out.append((render(subject_t, r["context"]),
                        render(body_t, r["context"]), sender, [r["email"]]))
    return tuple(out)


def total_recipients(groups):
    return sum(len(g["recipients"]) for g in groups)


# --- announcement workflow -------------------------------------------------


def _announcement_recipients(announcement):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    if announcement.audience == "officers":
        qs = User.objects.filter(is_officer=True, is_active=True)
    elif announcement.audience == "guests":
        qs = User.objects.filter(is_guest=True, is_active=True)
    else:
        qs = User.objects.filter(is_active=True)
    return [
        {"email": u.email, "name": str(u),
         "context": {"first_name": u.first_name}}
        for u in qs if u.email
    ]


def build_announcement_draft(announcement, back_url=""):
    recipients = _announcement_recipients(announcement)
    return {
        "workflow": "announcement",
        "title": f"Send announcement: {announcement.subject}",
        "back_url": back_url,
        "groups": [{
            "key": "all",
            "label": f"{announcement.get_audience_display()} ({len(recipients)})",
            "subject": announcement.subject,
            "body": announcement.body,
            "placeholders": ["first_name"],
            "recipients": recipients,
        }],
    }
