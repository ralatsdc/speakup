"""
Generic "review before send" page. Every deliberate email trigger (meeting
reminders/feedback, announcements, role invites) redirects here with a
``workflow`` and its target ids; the page shows exactly what will go out
(editable shared subject/body per group + a live preview), and only sends on
confirm.
"""

import json

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .emails import render as render_template, total_recipients


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

    if workflow == "announcement":
        from django.utils import timezone
        from .models import Announcement
        from .emails import build_announcement_draft
        from .utils import send_announcement

        ann = get_object_or_404(Announcement, pk=p.get("announcement"))

        def send(edits):
            count = send_announcement(ann, edits)
            ann.sent_at = timezone.now()
            ann.save(update_fields=["sent_at"])
            return f"Sent '{ann.subject}' to {count} recipient{'s' if count != 1 else ''}."
        return {"params": {"workflow": workflow, "announcement": ann.id},
                "default_back": reverse("admin:communications_announcement_change",
                                        args=[ann.id]),
                "build": lambda: build_announcement_draft(ann), "send": send}

    if workflow == "invite":
        from members.models import User
        from meetings.models import Role
        from meetings.emails import build_invite_draft
        from meetings.utils import send_role_invite

        member = get_object_or_404(User, pk=p.get("member"))
        role = get_object_or_404(Role, pk=p.get("role"), show_on_agenda=True)

        def send(edits):
            n = send_role_invite(member, role, edits)
            if n:
                return (f"Invited {member} to take {role.name} "
                        f"({n} upcoming meeting{'s' if n != 1 else ''} with it open).")
            return (f"Invited {member} to take {role.name} (linked to the sign-up "
                    f"page; no upcoming meeting currently has it open).")
        return {"params": {"workflow": workflow, "member": member.id, "role": role.id},
                "default_back": reverse(
                    "admin:members_user_activity_report_detail", args=[member.id]),
                "build": lambda: build_invite_draft(member, role), "send": send}

    return None


def _parse_edits(post, groups):
    edits = {}
    for g in groups:
        k = g["key"]
        edits[k] = {"subject": post.get(f"subject_{k}"),
                    "body": post.get(f"body_{k}")}
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
        g["preview_body"] = render_template(g["body"], ctx)


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
        edits = _parse_edits(request.POST, handler["build"]()["groups"])
        messages.success(request, handler["send"](edits))
        return redirect(back_url)

    draft = handler["build"]()
    _attach_previews(draft["groups"])
    return render(request, "communications/admin/email_review.html", {
        **admin.site.each_context(request),
        "title": draft["title"],
        "draft": draft,
        "back_url": back_url,
        "params": handler["params"],
        "total": total_recipients(draft["groups"]),
    })
