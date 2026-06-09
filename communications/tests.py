from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from meetings.models import Meeting, MeetingRole, Role
from members.models import User
from .models import Announcement


class EmailReviewTest(TestCase):
    """The shared review-before-send gate: GET renders the draft, POST sends
    (applying any edits) and runs each workflow's post-send hooks."""

    def setUp(self):
        self.staff = User.objects.create_superuser(
            "boss", "boss@example.com", "pw")
        self.client.force_login(self.staff)
        self.url = reverse("email_review")

    def _meeting(self):
        role = Role.objects.create(name="Toastmaster")
        m = Meeting.objects.create(
            date=timezone.now() + timedelta(days=3), theme="Growth")
        alice = User.objects.create_user(
            "alice", "alice@example.com", "pw", first_name="Alice")
        mr = MeetingRole.objects.create(
            meeting=m, role=role, user=alice, admin_notes="Well done")
        MeetingRole.objects.create(meeting=m, role=role, user=None)  # open slot
        return m, role, alice, mr

    # --- reminders ---

    def test_reminders_get_renders_both_groups(self):
        m, *_ = self._meeting()
        resp = self.client.get(self.url, {"workflow": "reminders", "meeting": m.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Assigned members")
        self.assertContains(resp, "Open-role nudge")

    def test_reminders_post_applies_edits(self):
        m, *_ = self._meeting()
        resp = self.client.post(self.url, {
            "workflow": "reminders", "meeting": m.id,
            "subject_assignees": "Custom {role}", "body_assignees": "Hi {first_name}!",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(any(msg.subject == "Custom Toastmaster" for msg in mail.outbox))
        self.assertTrue(any("Hi Alice!" in msg.body for msg in mail.outbox))

    # --- feedback ---

    def test_feedback_post_sends_and_stamps(self):
        m, role, alice, mr = self._meeting()
        resp = self.client.post(self.url, {"workflow": "feedback", "meeting": m.id})
        self.assertEqual(resp.status_code, 302)
        mr.refresh_from_db()
        self.assertEqual(mr.feedback_sent_notes, "Well done")  # stamped once
        self.assertTrue(any("Well done" in msg.body for msg in mail.outbox))

    # --- announcement ---

    def test_announcement_post_edits_and_stamps_sent_at(self):
        ann = Announcement.objects.create(subject="Hi", body="Body", audience="all")
        resp = self.client.post(self.url, {
            "workflow": "announcement", "announcement": ann.id,
            "subject_all": "Edited subject", "body_all": "Edited body",
        })
        self.assertEqual(resp.status_code, 302)
        ann.refresh_from_db()
        self.assertIsNotNone(ann.sent_at)
        self.assertTrue(any(msg.subject == "Edited subject" for msg in mail.outbox))

    # --- invite ---

    def test_invite_post_sends(self):
        role = Role.objects.create(name="Timer")
        bob = User.objects.create_user("bob", "bob@example.com", "pw", first_name="Bob")
        m = Meeting.objects.create(date=timezone.now() + timedelta(days=4))
        MeetingRole.objects.create(meeting=m, role=role, user=None)
        resp = self.client.post(self.url, {
            "workflow": "invite", "member": bob.id, "role": role.id})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(mail.outbox)
        self.assertIn("Timer", mail.outbox[-1].subject)
        self.assertEqual(mail.outbox[-1].to, ["bob@example.com"])

    def test_invite_post_multiple_roles_sends_one_email(self):
        tm = Role.objects.create(name="Toastmaster")
        timer = Role.objects.create(name="Timer")
        bob = User.objects.create_user("bob", "bob@example.com", "pw", first_name="Bob")
        m = Meeting.objects.create(date=timezone.now() + timedelta(days=4))
        MeetingRole.objects.create(meeting=m, role=tm, user=None)
        MeetingRole.objects.create(meeting=m, role=timer, user=None)
        resp = self.client.post(self.url, {
            "workflow": "invite", "member": bob.id, "role": [tm.id, timer.id]})
        self.assertEqual(resp.status_code, 302)
        # One invitation covering both roles, not one per role.
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["bob@example.com"])
        self.assertIn("Toastmaster", mail.outbox[0].body)
        self.assertIn("Timer", mail.outbox[0].body)

    def test_invite_get_with_no_roles_404(self):
        bob = User.objects.create_user("bob", "bob@example.com", "pw")
        resp = self.client.get(self.url, {"workflow": "invite", "member": bob.id})
        self.assertEqual(resp.status_code, 404)

    # --- guards ---

    def test_cancel_sends_nothing(self):
        ann = Announcement.objects.create(subject="Hi", body="Body", audience="all")
        resp = self.client.post(self.url, {
            "workflow": "announcement", "announcement": ann.id, "_cancel": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
        ann.refresh_from_db()
        self.assertIsNone(ann.sent_at)

    def test_unknown_workflow_404(self):
        self.assertEqual(
            self.client.get(self.url, {"workflow": "bogus"}).status_code, 404)

    def test_invite_off_agenda_role_404(self):
        pres = Role.objects.create(name="President", show_on_agenda=False)
        bob = User.objects.create_user("bob", "bob@example.com", "pw")
        resp = self.client.get(self.url, {
            "workflow": "invite", "member": bob.id, "role": pres.id})
        self.assertEqual(resp.status_code, 404)

    def test_requires_staff(self):
        self.client.logout()
        resp = self.client.get(self.url, {"workflow": "reminders", "meeting": 1})
        self.assertIn(resp.status_code, (302, 403))


class AnnouncementSendTest(TestCase):
    def setUp(self):
        self.member = User.objects.create_user(
            username="member", password="pass", email="member@example.com"
        )
        self.officer = User.objects.create_user(
            username="officer", password="pass", email="officer@example.com",
            is_officer=True,
        )
        self.guest = User.objects.create_user(
            username="guest", password="pass", email="guest@example.com",
            is_guest=True,
        )

    @patch("communications.emails.send_messages")
    def test_send_to_all(self, mock_send):
        announcement = Announcement.objects.create(
            subject="Hello", body="Test", audience="all"
        )
        announcement.send()
        mock_send.assert_called_once()
        messages = mock_send.call_args[0][0]
        self.assertEqual(len(messages), 3)

    @patch("communications.emails.send_messages")
    def test_send_to_officers(self, mock_send):
        announcement = Announcement.objects.create(
            subject="Officers only", body="Test", audience="officers"
        )
        announcement.send()
        messages = mock_send.call_args[0][0]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].to, ["officer@example.com"])

    @patch("communications.emails.send_messages")
    def test_send_to_guests(self, mock_send):
        announcement = Announcement.objects.create(
            subject="Guests only", body="Test", audience="guests"
        )
        announcement.send()
        messages = mock_send.call_args[0][0]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].to, ["guest@example.com"])


class MarkdownRenderingTest(TestCase):
    """Bodies are authored in Markdown; emails carry a clean plain-text part
    plus an HTML alternative."""

    def test_to_html_renders_markdown(self):
        from .emails import to_html

        html = to_html("Hi **there**, see [signups](https://x.test/s) — 🎉")
        self.assertIn("<strong>there</strong>", html)
        self.assertIn('<a href="https://x.test/s">signups</a>', html)
        self.assertIn("🎉", html)

    def test_to_text_strips_markdown(self):
        from .emails import to_text

        text = to_text("Hi **there**, see [signups](https://x.test/s) — 🎉")
        self.assertNotIn("**", text)
        self.assertNotIn("](", text)
        self.assertIn("there", text)
        self.assertIn("signups (https://x.test/s)", text)
        self.assertIn("🎉", text)

    def test_build_messages_attaches_html_alternative(self):
        from .emails import build_messages

        groups = [{
            "key": "all", "subject": "Subject 🎉",
            "body": "Hello **{first_name}**",
            "recipients": [{"email": "a@b.test", "name": "Al",
                            "context": {"first_name": "Al"}}],
        }]
        [msg] = build_messages(groups)
        # Plain-text body has the markers stripped...
        self.assertEqual(msg.body, "Hello Al")
        self.assertEqual(msg.subject, "Subject 🎉")
        # ...and there's exactly one text/html alternative with real bold.
        self.assertEqual(len(msg.alternatives), 1)
        html, mimetype = msg.alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn("<strong>Al</strong>", html)

    def test_announcement_email_is_multipart_with_bold(self):
        User.objects.create_user(
            username="m", password="pw", email="m@example.com", first_name="Mo")
        ann = Announcement.objects.create(
            subject="News", body="Hi **{first_name}** 🎉", audience="all")
        ann.send()
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.body, "Hi Mo 🎉")  # plain text, no markers
        self.assertIn("<strong>Mo</strong>", msg.alternatives[0][0])
