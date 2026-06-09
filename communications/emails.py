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

Builders produce a draft (no send). The subject/body templates are authored in
Markdown. ``build_messages`` applies per-group subject/body overrides (the edits
from the review form, falling back to the draft's own templates), renders each
recipient's copy, and returns ``EmailMultiAlternatives`` objects carrying a
clean plain-text body plus an HTML alternative rendered from the Markdown. The
per-app ``utils`` send functions own the actual ``send_messages`` call.
Placeholder substitution is forgiving: an unknown or fumbled ``{token}`` renders
blank rather than raising.
"""

import re

import markdown as md
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def render(template, context):
    r"""Substitute ``{name}`` tokens from ``context``; missing keys -> ''.
    Stray braces that don't match ``{\w+}`` are left untouched."""
    return _PLACEHOLDER.sub(lambda m: str(context.get(m.group(1), "")), template or "")


# --- Markdown rendering ----------------------------------------------------

_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|_)(.+?)\1")
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)

_HTML_TEMPLATE = (
    '<!DOCTYPE html><html><body style="font-family:-apple-system,Segoe UI,'
    'Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;'
    'color:#222;">{inner}</body></html>'
)


def to_html(text):
    """Render Markdown ``text`` to a standalone HTML document. Single newlines
    become ``<br>`` (``nl2br``) so bodies authored as plain paragraphs keep
    their line breaks; ``extra`` covers links, lists, bold/italic, etc."""
    inner = md.markdown(text or "", extensions=["extra", "nl2br", "sane_lists"])
    return _HTML_TEMPLATE.format(inner=inner)


def to_text(text):
    """Best-effort plain-text rendering of Markdown ``text``: turn
    ``[label](url)`` into ``label (url)`` and strip emphasis/heading markers so
    text-only clients don't see literal ``**`` or ``#``. Leaves list dashes and
    everything else intact."""
    text = _MD_LINK.sub(r"\1 (\2)", text or "")
    text = _MD_HEADING.sub("", text)
    # Collapse emphasis markers, innermost first (handles ``**bold**`` then any
    # remaining single-marker emphasis).
    for _ in range(2):
        text = _MD_EMPHASIS.sub(r"\2", text)
    return text


# --- message building / sending --------------------------------------------


def build_messages(groups, edits=None):
    """Turn draft groups into ``EmailMultiAlternatives`` (plain-text body + HTML
    alternative), applying ``edits`` (``{group_key: {"subject": ..., "body":
    ...}}``) over the defaults."""
    edits = edits or {}
    sender = settings.DEFAULT_FROM_EMAIL
    out = []
    for group in groups:
        override = edits.get(group["key"], {})
        subject_t = override.get("subject") or group["subject"]
        body_t = override.get("body") or group["body"]
        for r in group["recipients"]:
            subject = render(subject_t, r["context"])
            body_md = render(body_t, r["context"])
            msg = EmailMultiAlternatives(
                subject, to_text(body_md), sender, [r["email"]])
            msg.attach_alternative(to_html(body_md), "text/html")
            out.append(msg)
    return out


def send_messages(messages):
    """Send pre-built ``EmailMultiAlternatives`` over a single connection.
    Returns the number of messages accepted for delivery."""
    if not messages:
        return 0
    return get_connection().send_messages(messages) or 0


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
