"""
Generic "review before send" page. Every deliberate email trigger (meeting
reminders/feedback, announcements, role invites) redirects here with a
``workflow`` and its target ids; the page shows exactly what will go out
(editable shared subject/body per group + a live preview), and only sends on
confirm.
"""

import json
import logging
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import individual
from .emails import (active_senders, default_sender, render as render_template,
                     to_html, total_recipients)
from .models import Announcement, AnnouncementDelivery

logger = logging.getLogger(__name__)


def _resolve_handler(workflow, request):
    """Return a handler dict for ``workflow`` (resolving its target from the
    request), or None if unknown. 404s if the target doesn't exist."""
    p = request.POST if request.method == "POST" else request.GET

    if workflow in ("reminders", "feedback"):
        from meetings.models import Meeting
        from meetings.emails import build_reminder_draft, build_feedback_draft
        from meetings.utils import send_meeting_reminders, send_meeting_feedback

        meeting = get_object_or_404(Meeting, pk=p.get("meeting"))
        params = {"workflow": workflow, "meeting": meeting.id}
        back = reverse("admin:meetings_meeting_change", args=[meeting.id])
        if workflow == "reminders":
            def send(edits):
                n = send_meeting_reminders(meeting, edits)
                return f"Sent {n} reminder email{'s' if n != 1 else ''}."
            return {"params": params, "default_back": back,
                    "build": lambda: build_reminder_draft(meeting), "send": send}

        def send(edits):
            fc, gc = send_meeting_feedback(meeting, edits)
            parts = []
            if fc:
                parts.append(f"feedback to {fc} member{'s' if fc != 1 else ''}")
            if gc:
                parts.append(f"thank-yous to {gc} guest{'s' if gc != 1 else ''}")
            return "Sent " + (", ".join(parts) if parts else "nothing") + "."
        return {"params": params, "default_back": back,
                "build": lambda: build_feedback_draft(meeting), "send": send}

    if workflow == "register":
        from meetings.models import Meeting
        from meetings.emails import build_register_draft
        from meetings.utils import send_meeting_register_reminders

        meeting = get_object_or_404(Meeting, pk=p.get("meeting"))

        def send(edits):
            n = send_meeting_register_reminders(meeting, edits)
            return f"Sent {n} registration reminder{'s' if n != 1 else ''}."
        return {"params": {"workflow": workflow, "meeting": meeting.id},
                "default_back": reverse("admin:meetings_meeting_change",
                                        args=[meeting.id]),
                "build": lambda: build_register_draft(meeting), "send": send}

    if workflow == "announcement":
        from django.utils import timezone
        from .emails import build_announcement_draft
        from .utils import send_announcements

        # One id from the change-form button, or several from the changelist's
        # bulk action. Same round-trip shape as the invite workflow: repeated
        # ``announcement=1&announcement=2`` in, comma-joined back out through
        # the review form's single hidden field.
        raw = p.getlist("announcement") or (p.get("announcements") or "").split(",")
        ann_ids = []
        for x in raw:
            if x.isdigit() and int(x) not in ann_ids:
                ann_ids.append(int(x))
        if not ann_ids:
            raise Http404("No announcements selected")
        anns = [get_object_or_404(Announcement, pk=aid) for aid in ann_ids]

        def send(edits):
            with transaction.atomic():
                # Locked so a one-at-a-time send can't slip in between working
                # out who is left and mailing them.
                locked = list(Announcement.objects.select_for_update().filter(
                    pk__in=[a.pk for a in anns]).order_by("pk"))
                unsent = {a.pk for a in locked if individual.everyone_skipped(a)}
                count = send_announcements(anns, edits)
                now = timezone.now()
                for a in anns:
                    if a.pk in unsent:
                        continue
                    a.sent_at = now
                    a.save(update_fields=["sent_at"])
            plural = "s" if count != 1 else ""
            if len(anns) == 1:
                return f"Sent '{anns[0].subject}' to {count} recipient{plural}."
            return f"Sent {len(anns)} announcements to {count} recipient{plural}."

        back = (reverse("admin:communications_announcement_change", args=[anns[0].id])
                if len(anns) == 1
                else reverse("admin:communications_announcement_changelist"))
        return {"params": {"workflow": workflow,
                           "announcements": ",".join(str(a.id) for a in anns)},
                "default_back": back,
                "build": lambda: build_announcement_draft(anns), "send": send}

    if workflow == "invite":
        from members.models import User
        from meetings.models import Role
        from meetings.emails import build_invite_draft, role_phrase
        from meetings.utils import send_role_invite

        member = get_object_or_404(User, pk=p.get("member"))
        # Roles arrive either as repeated ``role=1&role=2`` (the activity-report
        # checkboxes) or comma-joined ``roles=1,2`` (round-tripped through the
        # review form's single hidden field). De-dupe, preserve order.
        raw = p.getlist("role") or (p.get("roles") or "").split(",")
        role_ids = []
        for x in raw:
            if x.isdigit() and int(x) not in role_ids:
                role_ids.append(int(x))
        if not role_ids:
            raise Http404("No roles selected")
        roles = [get_object_or_404(Role, pk=rid, show_on_agenda=True)
                 for rid in role_ids]
        phrase = role_phrase(roles)

        def send(edits):
            n = send_role_invite(member, roles, edits)
            if n:
                return (f"Invited {member} to take {phrase} "
                        f"({n} upcoming meeting{'s' if n != 1 else ''} with an open slot).")
            return (f"Invited {member} to take {phrase} (linked to the sign-up "
                    f"page; no upcoming meeting currently has these open).")
        return {"params": {"workflow": workflow, "member": member.id,
                           "roles": ",".join(str(r.id) for r in roles)},
                "default_back": reverse(
                    "admin:members_user_activity_report_detail", args=[member.id]),
                "build": lambda: build_invite_draft(member, roles), "send": send}

    return None


def _parse_edits(post, groups):
    edits = {}
    for g in groups:
        k = g["key"]
        edits[k] = {"subject": post.get(f"subject_{k}"),
                    "body": post.get(f"body_{k}"),
                    "sender": post.get(f"sender_{k}")}
    return edits


def _attach_previews(groups):
    """Add a server-rendered sample preview + JSON context (for live JS) to each
    group, using the first recipient."""
    for g in groups:
        sample = g["recipients"][0] if g["recipients"] else None
        ctx = sample["context"] if sample else {}
        g["sample_name"] = sample["name"] if sample else ""
        g["sample_context_json"] = json.dumps(ctx, default=str)
        g["preview_subject"] = render_template(g["subject"], ctx)
        # Server-rendered HTML for the first paint (and a no-JS fallback); the
        # client re-renders Markdown live as the body is edited.
        g["preview_body_html"] = to_html(render_template(g["body"], ctx))


@staff_member_required
def email_review(request):
    workflow = request.POST.get("workflow") or request.GET.get("workflow")
    handler = _resolve_handler(workflow, request)
    if handler is None:
        raise Http404("Unknown email workflow")

    back_url = (request.POST.get("back") or request.GET.get("back")
                or handler["default_back"])

    if request.method == "POST":
        if "_cancel" in request.POST:
            return redirect(back_url)
        try:
            edits = _parse_edits(request.POST, handler["build"]()["groups"])
            result = handler["send"](edits)
        except Exception as e:
            # e.g. the Zoom API is unreachable while building the register
            # draft — surface the error instead of 500-ing or sending blindly.
            messages.error(request, f"Could not send the email: {e}")
            return redirect(back_url)
        messages.success(request, result)
        return redirect(back_url)

    try:
        draft = handler["build"]()
    except Exception as e:
        messages.error(request, f"Could not build the email: {e}")
        return redirect(back_url)
    _attach_previews(draft["groups"])
    return render(request, "communications/admin/email_review.html", {
        **admin.site.each_context(request),
        "title": draft["title"],
        "draft": draft,
        "back_url": back_url,
        "params": handler["params"],
        "total": total_recipients(draft["groups"]),
        "default_sender": default_sender(),
        "senders": active_senders(),
    })


@staff_member_required
def send_one_at_a_time(request):
    """Step through an announcement's recipients, customizing each message.
    Shows the next person waiting; each action redirects back here."""
    if not request.user.has_perm("communications.change_announcement"):
        raise PermissionDenied
    params = request.POST if request.method == "POST" else request.GET
    pk = params.get("announcement", "")
    if not pk.isdigit():
        raise Http404("No announcement selected")
    announcement = get_object_or_404(Announcement, pk=pk)
    sender_id = params.get("sender", "")
    here = reverse("email_each") + "?" + urlencode(
        {"announcement": announcement.pk, "sender": sender_id})
    back_url = reverse("admin:communications_announcement_change",
                       args=[announcement.pk])
    draft = None  # the officer's text, kept if a send fails

    if request.method == "POST":
        if "_later" in request.POST:
            return redirect(back_url)
        user_id = _int_or_none(request.POST.get("user"))
        try:
            if "_send" in request.POST:
                subject = request.POST.get("subject", "")
                body = request.POST.get("body", "")
                draft = {"user_id": user_id, "subject": subject, "body": body}
                if not (subject.strip() and body.strip()):
                    messages.error(request, "Enter both a subject and a body.")
                else:
                    delivery, completed = individual.send_one(
                        announcement.pk, user_id, request.user,
                        subject, body, sender_id)
                    messages.success(request, f"Sent to {delivery.name}.")
                    return _after_step(request, completed, here)
            elif "_skip" in request.POST:
                delivery, completed = individual.skip_one(
                    announcement.pk, user_id, request.user)
                messages.success(request, f"Skipped {delivery.name}.")
                return _after_step(request, completed, here)
            elif "_restore" in request.POST:
                individual.restore(
                    announcement.pk,
                    _int_or_none(request.POST.get("_restore")))
                return redirect(here)
            elif "_complete" in request.POST:
                individual.complete(announcement.pk)
                return _after_step(request, True, here)
            else:
                return redirect(here)
        except individual.NotAvailable as e:
            messages.warning(request, str(e))
            return redirect(here)
        except Exception as e:
            logger.exception("One-at-a-time send failed: %s", announcement)
            messages.error(request, f"Could not send the email: {e}")

    try:
        waiting = ([] if announcement.sent_at
                   else individual.remaining(announcement))
    except ValueError as e:
        messages.error(request, f"Could not build the email: {e}")
        return redirect(back_url)

    deliveries = list(announcement.deliveries.all())
    current = waiting[0] if waiting else None
    if draft:
        # Stay on the person whose send failed.
        match = next(
            (r for r in waiting if r["user_id"] == draft["user_id"]), None)
        if match:
            current = match
        else:
            draft = None

    group = None
    if current:
        context = current["context"]
        group = {
            "key": "one",
            "subject": (draft["subject"] if draft else
                        render_template(announcement.subject, context)),
            "body": (draft["body"] if draft else
                     render_template(announcement.body, context)),
            "recipients": [current],
        }
        _attach_previews([group])

    return render(request, "communications/admin/email_each.html", {
        **admin.site.each_context(request),
        "title": f"Send one at a time: {announcement.subject}",
        "announcement": announcement,
        "back_url": back_url,
        "current": current,
        "group": group,
        "position": len(deliveries) + 1,
        "total": len(deliveries) + len(waiting),
        "is_last": len(waiting) == 1,
        "up_next": [r for r in waiting if r is not current],
        "deliveries": deliveries,
        "sent_count": sum(d.status == AnnouncementDelivery.SENT
                          for d in deliveries),
        "default_sender": default_sender(),
        "senders": active_senders(),
        "sender_id": sender_id,
    })


def _int_or_none(value):
    return int(value) if value and value.isdigit() else None


def _after_step(request, completed, here):
    if completed:
        messages.success(
            request, "Everyone has been handled. The announcement is complete.")
    return redirect(here)
