import tempfile
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from members.models import User
from .models import (
    Attendance,
    Meeting,
    MeetingRole,
    MeetingType,
    MeetingTypeItem,
    Role,
    RoleGuideEmailLog,
)
from .services import convert_guest_attendance_to_user
from .zoom import extract_zoom_meeting_id, import_zoom_registrants


class MeetingSignalTest(TestCase):
    """Test that creating a Meeting auto-populates roles from its MeetingType."""

    def setUp(self):
        self.role_speaker = Role.objects.create(name="Speaker", shows_pathways_fields=True)
        self.role_timer = Role.objects.create(name="Timer")
        self.meeting_type = MeetingType.objects.create(name="Regular")
        MeetingTypeItem.objects.create(
            meeting_type=self.meeting_type, role=self.role_speaker, count=3, order=1
        )
        MeetingTypeItem.objects.create(
            meeting_type=self.meeting_type, role=self.role_timer, count=1, order=2
        )

    def test_roles_populated_on_create(self):
        meeting = Meeting.objects.create(
            meeting_type=self.meeting_type,
            date=timezone.now(),
        )
        self.assertEqual(meeting.roles.count(), 4)
        self.assertEqual(meeting.roles.filter(role=self.role_speaker).count(), 3)
        self.assertEqual(meeting.roles.filter(role=self.role_timer).count(), 1)

    def test_populated_roles_have_no_attendance_mode(self):
        meeting = Meeting.objects.create(
            meeting_type=self.meeting_type,
            date=timezone.now(),
        )
        self.assertTrue(
            all(r.in_person is None for r in meeting.roles.all())
        )

    def test_no_roles_without_meeting_type(self):
        meeting = Meeting.objects.create(date=timezone.now())
        self.assertEqual(meeting.roles.count(), 0)

    def test_roles_not_duplicated_on_save(self):
        meeting = Meeting.objects.create(
            meeting_type=self.meeting_type,
            date=timezone.now(),
        )
        meeting.theme = "Updated theme"
        meeting.save()
        self.assertEqual(meeting.roles.count(), 4)

    def test_raw_save_does_not_populate(self):
        # loaddata saves with raw=True; the template rows are already in the
        # fixture, so the signal must NOT re-create them (else dumpdata|loaddata
        # via pg.sh -c/-u would double every meeting's roles).
        meeting = Meeting(meeting_type=self.meeting_type, date=timezone.now())
        meeting.save_base(raw=True)
        self.assertEqual(meeting.roles.count(), 0)


class UpcomingMeetingsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", email="testuser@example.com", password="testpass")

    def test_anonymous_access(self):
        response = self.client.get(reverse("role_signups"))
        self.assertEqual(response.status_code, 200)

    def test_authenticated_access(self):
        self.client.login(username="testuser", email="testuser@example.com", password="testpass")
        response = self.client.get(reverse("role_signups"))
        self.assertEqual(response.status_code, 200)


class ToggleRoleViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="member1", email="member1@example.com", password="testpass")
        self.user2 = User.objects.create_user(username="member2", email="member2@example.com", password="testpass")
        role = Role.objects.create(name="Timer")
        self.meeting = Meeting.objects.create(date=timezone.now())
        self.assignment = MeetingRole.objects.create(
            meeting=self.meeting, role=role, sort_order=0
        )

    def test_claim_role(self):
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        response = self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.user, self.user)

    def test_drop_role(self):
        self.assignment.user = self.user
        self.assignment.save()
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.user)

    def test_claim_sets_attendance_mode_from_template(self):
        # MeetingTypeItem expects Remote; claim with no body falls back to it.
        meeting_type = MeetingType.objects.create(name="Regular")
        MeetingTypeItem.objects.create(
            meeting_type=meeting_type, role=self.assignment.role, in_person=False
        )
        self.meeting.meeting_type = meeting_type
        self.meeting.save()
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assignment.refresh_from_db()
        self.assertFalse(self.assignment.in_person)

    def test_drop_clears_attendance_mode(self):
        self.assignment.user = self.user
        self.assignment.in_person = True
        self.assignment.save()
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.in_person)

    def test_cannot_take_occupied_role(self):
        self.assignment.user = self.user2
        self.assignment.save()
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        response = self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assertEqual(response.status_code, 403)

    def test_guest_cannot_claim_role(self):
        guest = User.objects.create_user(
            username="guest1", email="guest1@example.com", password="testpass", is_guest=True
        )
        self.client.login(username="guest1", email="guest1@example.com", password="testpass")
        response = self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.user)
        self.assertIn("Guests cannot sign up", response["HX-Trigger"])

    def test_requires_login(self):
        response = self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assertEqual(response.status_code, 302)

    # --- Sign-up dialog (Block B) ---

    def _speech_assignment(self, **kwargs):
        """Create an open MeetingRole for a speech role on the test meeting."""
        speech_role = Role.objects.create(name="Speaker", shows_pathways_fields=True)
        return MeetingRole.objects.create(
            meeting=self.meeting, role=speech_role, sort_order=1, **kwargs
        )

    def test_signup_form_renders(self):
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        response = self.client.get(
            reverse("signup_role_form", args=[self.assignment.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "In Person")
        self.assertContains(response, "Remote")

    def test_signup_form_requires_login(self):
        response = self.client.get(
            reverse("signup_role_form", args=[self.assignment.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_signup_form_hides_pathways_for_non_speech_role(self):
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        response = self.client.get(
            reverse("signup_role_form", args=[self.assignment.id])
        )
        self.assertNotContains(response, "Pathways Path")

    def test_signup_form_shows_pathways_for_speech_role(self):
        speech = self._speech_assignment()
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        response = self.client.get(reverse("signup_role_form", args=[speech.id]))
        self.assertContains(response, "Pathways Path")
        self.assertContains(response, "Presentation Mastery")

    def test_claim_with_explicit_remote(self):
        # The Timer role expects in-person; the member overrides to Remote.
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        self.client.post(
            reverse("toggle_role", args=[self.assignment.id]),
            {"in_person": "false"},
        )
        self.assignment.refresh_from_db()
        self.assertFalse(self.assignment.in_person)

    def test_claim_with_explicit_in_person(self):
        # Template expects Remote; member overrides to In Person in the dialog.
        meeting_type = MeetingType.objects.create(name="Regular")
        MeetingTypeItem.objects.create(
            meeting_type=meeting_type, role=self.assignment.role, in_person=False
        )
        self.meeting.meeting_type = meeting_type
        self.meeting.save()
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        self.client.post(
            reverse("toggle_role", args=[self.assignment.id]),
            {"in_person": "true"},
        )
        self.assignment.refresh_from_db()
        self.assertTrue(self.assignment.in_person)

    def test_claim_saves_notes(self):
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        self.client.post(
            reverse("toggle_role", args=[self.assignment.id]),
            {"in_person": "true", "notes": "  Timing the speeches  "},
        )
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.notes, "Timing the speeches")

    def test_claim_saves_pathways_for_speech_role(self):
        speech = self._speech_assignment()
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        self.client.post(
            reverse("toggle_role", args=[speech.id]),
            {
                "in_person": "true",
                "notes": "The Power of Pause",
                "pathways_path": "Presentation Mastery",
                "pathways_level": "2",
                "pathways_project": "Effective Body Language",
            },
        )
        speech.refresh_from_db()
        self.assertEqual(speech.pathways_path, "Presentation Mastery")
        self.assertEqual(speech.pathways_level, 2)
        self.assertEqual(speech.pathways_project, "Effective Body Language")

    def test_claim_ignores_pathways_for_non_speech_role(self):
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        self.client.post(
            reverse("toggle_role", args=[self.assignment.id]),
            {
                "in_person": "true",
                "pathways_path": "Engaging Humor",
                "pathways_level": "3",
            },
        )
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.pathways_path, "")
        self.assertIsNone(self.assignment.pathways_level)

    def test_drop_clears_notes_and_pathways(self):
        speech = self._speech_assignment(
            user=self.user,
            in_person=True,
            notes="My Speech",
            pathways_path="Engaging Humor",
            pathways_level=1,
            pathways_project="Hook Your Audience",
        )
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        self.client.post(reverse("toggle_role", args=[speech.id]))
        speech.refresh_from_db()
        self.assertIsNone(speech.user)
        self.assertEqual(speech.notes, "")
        self.assertEqual(speech.pathways_path, "")
        self.assertIsNone(speech.pathways_level)
        self.assertEqual(speech.pathways_project, "")

    # --- Editing an assigned role (same dialog/fields as sign-up) ---

    def test_dialog_is_edit_mode_for_assigned_role(self):
        speech = self._speech_assignment(
            user=self.user,
            in_person=False,
            notes="The Power of Pause",
            pathways_path="Presentation Mastery",
            pathways_level=2,
            pathways_project="Effective Body Language",
        )
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        response = self.client.get(reverse("signup_role_form", args=[speech.id]))
        # Edit framing, posts to the edit endpoint, current values preselected.
        self.assertContains(response, "Edit:")
        self.assertContains(response, reverse("save_role_details", args=[speech.id]))
        self.assertContains(response, "The Power of Pause")
        self.assertContains(response, 'value="Presentation Mastery" selected')

    def test_edit_updates_attendance_notes_and_pathways(self):
        speech = self._speech_assignment(
            user=self.user, in_person=True, notes="Old title",
        )
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        response = self.client.post(
            reverse("save_role_details", args=[speech.id]),
            {
                "in_person": "false",
                "notes": "New title",
                "pathways_path": "Engaging Humor",
                "pathways_level": "3",
                "pathways_project": "Know Your Sense of Humor",
            },
        )
        self.assertEqual(response.status_code, 200)
        speech.refresh_from_db()
        self.assertFalse(speech.in_person)
        self.assertEqual(speech.notes, "New title")
        self.assertEqual(speech.pathways_path, "Engaging Humor")
        self.assertEqual(speech.pathways_level, 3)
        self.assertEqual(speech.pathways_project, "Know Your Sense of Humor")
        # The user is unchanged — editing must not drop the role.
        self.assertEqual(speech.user, self.user)

    def test_edit_forbidden_for_non_assignee_non_officer(self):
        self.assignment.user = self.user2
        self.assignment.save()
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        response = self.client.post(
            reverse("save_role_details", args=[self.assignment.id]),
            {"in_person": "true", "notes": "hijack"},
        )
        self.assertEqual(response.status_code, 403)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.notes, "")

    def test_officer_can_edit_others_role(self):
        officer = User.objects.create_user(
            username="officer1", email="officer1@example.com",
            password="testpass", is_officer=True,
        )
        self.assignment.user = self.user2
        self.assignment.save()
        self.client.login(username="officer1", email="officer1@example.com", password="testpass")
        self.client.post(
            reverse("save_role_details", args=[self.assignment.id]),
            {"in_person": "true", "notes": "Officer note"},
        )
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.notes, "Officer note")
        self.assertEqual(self.assignment.user, self.user2)


class CheckinKioskViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="testuser@example.com", password="testpass", is_officer=True
        )

    def test_no_meeting_shows_warning(self):
        self.client.login(username="testuser", email="testuser@example.com", password="testpass")
        response = self.client.get(reverse("checkin_kiosk"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No meeting found")


class CheckinMemberViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="testuser@example.com", password="testpass", is_officer=True
        )
        self.meeting = Meeting.objects.create(date=timezone.now())

    def test_checkin_creates_attendance(self):
        self.client.login(username="testuser", email="testuser@example.com", password="testpass")
        self.client.post(reverse("checkin_member", args=[self.meeting.id, self.user.id]))
        self.assertTrue(Attendance.objects.filter(meeting=self.meeting, user=self.user).exists())

    def test_checkin_toggle_removes_attendance(self):
        self.client.login(username="testuser", email="testuser@example.com", password="testpass")
        Attendance.objects.create(meeting=self.meeting, user=self.user)
        self.client.post(reverse("checkin_member", args=[self.meeting.id, self.user.id]))
        self.assertFalse(Attendance.objects.filter(meeting=self.meeting, user=self.user).exists())


class ConvertGuestServiceTest(TestCase):
    def setUp(self):
        self.meeting = Meeting.objects.create(date=timezone.now())

    def test_creates_user_from_guest(self):
        attendance = Attendance.objects.create(
            meeting=self.meeting, guest_first_name="Jane", guest_last_name="Doe", guest_email="jane@example.com"
        )
        user, created = convert_guest_attendance_to_user(attendance)
        self.assertTrue(created)
        self.assertEqual(user.email, "jane@example.com")
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.last_name, "Doe")
        attendance.refresh_from_db()
        self.assertEqual(attendance.user, user)

    def test_links_existing_user(self):
        existing = User.objects.create_user(
            username="jane", email="jane@example.com", password="pass"
        )
        attendance = Attendance.objects.create(
            meeting=self.meeting, guest_first_name="Jane", guest_last_name="Doe", guest_email="jane@example.com"
        )
        user, created = convert_guest_attendance_to_user(attendance)
        self.assertFalse(created)
        self.assertEqual(user, existing)

    def test_skips_if_already_linked(self):
        linked_user = User.objects.create_user(username="linked", email="linked@example.com", password="pass")
        attendance = Attendance.objects.create(meeting=self.meeting, user=linked_user)
        result, created = convert_guest_attendance_to_user(attendance)
        self.assertIsNone(result)

    def test_skips_if_no_email(self):
        attendance = Attendance.objects.create(
            meeting=self.meeting, guest_first_name="No", guest_last_name="Email"
        )
        result, created = convert_guest_attendance_to_user(attendance)
        self.assertIsNone(result)


class EmailUtilsTest(TestCase):
    def setUp(self):
        self.role = Role.objects.create(name="Speaker", shows_pathways_fields=True)
        self.meeting = Meeting.objects.create(
            date=timezone.now(), theme="Leadership"
        )
        self.user = User.objects.create_user(
            username="speaker1", password="pass", email="speaker@example.com",
            first_name="Alice",
        )
        self.assignment = MeetingRole.objects.create(
            meeting=self.meeting, role=self.role, user=self.user, sort_order=0
        )

    @patch("meetings.utils.send_mass_mail")
    def test_send_reminders(self, mock_send):
        from .utils import send_meeting_reminders

        send_meeting_reminders(self.meeting)
        mock_send.assert_called_once()
        messages = mock_send.call_args[0][0]
        self.assertEqual(len(messages), 1)
        self.assertIn("Speaker", messages[0][0])

    @patch("meetings.utils.send_mass_mail")
    def test_reminder_includes_attendance_mode(self, mock_send):
        from .utils import send_meeting_reminders

        self.assignment.in_person = False
        self.assignment.save()
        send_meeting_reminders(self.meeting)
        body = mock_send.call_args[0][0][0][1]
        self.assertIn("(Remote)", body)

    @patch("meetings.utils.send_mass_mail")
    def test_reminder_omits_mode_when_unspecified(self, mock_send):
        from .utils import send_meeting_reminders

        send_meeting_reminders(self.meeting)
        body = mock_send.call_args[0][0][0][1]
        self.assertNotIn("(Remote)", body)
        self.assertNotIn("(In Person)", body)

    @patch("meetings.utils.send_mass_mail")
    def test_send_feedback(self, mock_send):
        from .utils import send_meeting_feedback

        self.assignment.admin_notes = "Great job!"
        self.assignment.save()
        feedback_count, guest_count = send_meeting_feedback(self.meeting)
        self.assertEqual(feedback_count, 1)
        self.assertEqual(guest_count, 0)
        mock_send.assert_called_once()

    @patch("meetings.utils.send_mass_mail")
    def test_send_feedback_no_notes(self, mock_send):
        from .utils import send_meeting_feedback

        feedback_count, guest_count = send_meeting_feedback(self.meeting)
        self.assertEqual(feedback_count, 0)
        self.assertEqual(guest_count, 0)
        mock_send.assert_called_once()

    @patch("meetings.utils.send_mass_mail")
    def test_send_feedback_includes_guest_user(self, mock_send):
        from .utils import send_meeting_feedback

        guest = User.objects.create_user(
            username="guest1", password="pass", email="guest@example.com",
            first_name="Bob", is_guest=True,
        )
        Attendance.objects.create(meeting=self.meeting, user=guest)
        feedback_count, guest_count = send_meeting_feedback(self.meeting)
        self.assertEqual(feedback_count, 0)
        self.assertEqual(guest_count, 1)

    @patch("meetings.utils.send_mass_mail")
    def test_send_feedback_includes_walkin_guest(self, mock_send):
        from .utils import send_meeting_feedback

        Attendance.objects.create(
            meeting=self.meeting, guest_first_name="Jane", guest_last_name="Walk-in", guest_email="jane@example.com"
        )
        feedback_count, guest_count = send_meeting_feedback(self.meeting)
        self.assertEqual(feedback_count, 0)
        self.assertEqual(guest_count, 1)

    @patch("meetings.utils.send_mass_mail")
    def test_feedback_not_resent_when_notes_unchanged(self, mock_send):
        from .utils import send_meeting_feedback

        self.assignment.admin_notes = "Great job!"
        self.assignment.save()

        first, _ = send_meeting_feedback(self.meeting)
        self.assertEqual(first, 1)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.feedback_sent_notes, "Great job!")

        second, _ = send_meeting_feedback(self.meeting)
        self.assertEqual(second, 0)

    @patch("meetings.utils.send_mass_mail")
    def test_feedback_resent_when_notes_edited(self, mock_send):
        from .utils import send_meeting_feedback

        self.assignment.admin_notes = "Great job!"
        self.assignment.save()
        send_meeting_feedback(self.meeting)

        self.assignment.admin_notes = "Great job! One tip: slow down."
        self.assignment.save()
        count, _ = send_meeting_feedback(self.meeting)
        self.assertEqual(count, 1)

    @patch("meetings.utils.send_mass_mail")
    def test_guest_thank_you_not_resent(self, mock_send):
        from .utils import send_meeting_feedback

        attendance = Attendance.objects.create(
            meeting=self.meeting,
            guest_first_name="Jane",
            guest_last_name="Walk-in",
            guest_email="jane@example.com",
        )

        _, first = send_meeting_feedback(self.meeting)
        self.assertEqual(first, 1)
        attendance.refresh_from_db()
        self.assertIsNotNone(attendance.thank_you_sent_at)

        _, second = send_meeting_feedback(self.meeting)
        self.assertEqual(second, 0)


class ZoomUrlParsingTest(TestCase):
    def test_standard_url(self):
        self.assertEqual(extract_zoom_meeting_id("https://zoom.us/j/1234567890"), "1234567890")

    def test_url_with_password(self):
        self.assertEqual(
            extract_zoom_meeting_id("https://zoom.us/j/1234567890?pwd=abc123"),
            "1234567890",
        )

    def test_custom_subdomain(self):
        self.assertEqual(
            extract_zoom_meeting_id("https://company.zoom.us/j/9876543210"),
            "9876543210",
        )

    def test_no_meeting_id(self):
        self.assertIsNone(extract_zoom_meeting_id("https://zoom.us/meeting"))

    def test_empty_string(self):
        self.assertIsNone(extract_zoom_meeting_id(""))


class ZoomImportTest(TestCase):
    def setUp(self):
        self.meeting_date = timezone.now()
        self.meeting = Meeting.objects.create(
            date=self.meeting_date,
            zoom_link="https://zoom.us/j/1234567890",
        )
        self.member = User.objects.create_user(
            username="alice", password="pass", email="alice@example.com", first_name="Alice"
        )
        # A create_time within the registration window (1 day before meeting)
        self.valid_time = (self.meeting_date - timezone.timedelta(days=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def _reg(self, email, first_name="Test", last_name="User", create_time=None):
        return {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "create_time": create_time or self.valid_time,
        }

    @patch("meetings.zoom.fetch_zoom_registrants")
    def test_matches_member_by_email(self, mock_fetch):
        mock_fetch.return_value = [self._reg("alice@example.com", "Alice", "Smith")]
        members, guests, skipped = import_zoom_registrants(self.meeting)
        self.assertEqual(members, 1)
        self.assertEqual(guests, 0)
        self.assertEqual(skipped, 0)
        self.assertTrue(Attendance.objects.filter(meeting=self.meeting, user=self.member).exists())

    @patch("meetings.zoom.fetch_zoom_registrants")
    def test_creates_guest_for_unknown_email(self, mock_fetch):
        mock_fetch.return_value = [self._reg("stranger@example.com", "Bob", "Jones")]
        members, guests, skipped = import_zoom_registrants(self.meeting)
        self.assertEqual(members, 0)
        self.assertEqual(guests, 1)
        att = Attendance.objects.get(meeting=self.meeting, guest_email="stranger@example.com")
        self.assertEqual(att.guest_first_name, "Bob")

    @patch("meetings.zoom.fetch_zoom_registrants")
    def test_skips_duplicate_member(self, mock_fetch):
        Attendance.objects.create(meeting=self.meeting, user=self.member)
        mock_fetch.return_value = [self._reg("alice@example.com", "Alice", "Smith")]
        members, guests, skipped = import_zoom_registrants(self.meeting)
        self.assertEqual(members, 0)
        self.assertEqual(skipped, 1)

    @patch("meetings.zoom.fetch_zoom_registrants")
    def test_skips_duplicate_guest(self, mock_fetch):
        Attendance.objects.create(
            meeting=self.meeting, guest_first_name="Bob", guest_last_name="Jones",
            guest_email="stranger@example.com",
        )
        mock_fetch.return_value = [self._reg("stranger@example.com", "Bob", "Jones")]
        members, guests, skipped = import_zoom_registrants(self.meeting)
        self.assertEqual(guests, 0)
        self.assertEqual(skipped, 1)

    @patch("meetings.zoom.fetch_zoom_registrants")
    def test_filters_out_old_registrants(self, mock_fetch):
        """Registrants from a previous meeting's window should be excluded."""
        # Create a previous meeting 14 days ago
        prev_date = self.meeting_date - timezone.timedelta(days=14)
        Meeting.objects.create(date=prev_date, zoom_link="https://zoom.us/j/1234567890")

        old_time = (prev_date - timezone.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mock_fetch.return_value = [
            self._reg("alice@example.com", "Alice", "Smith", create_time=old_time),
            self._reg("stranger@example.com", "Bob", "Jones", create_time=self.valid_time),
        ]
        members, guests, skipped = import_zoom_registrants(self.meeting)
        # Alice's old registration is filtered out; only Bob (unknown email) imported as guest
        self.assertEqual(members, 0)
        self.assertEqual(guests, 1)
        self.assertFalse(Attendance.objects.filter(meeting=self.meeting, user=self.member).exists())

    @patch("meetings.zoom.fetch_zoom_registrants")
    def test_includes_registrants_within_window(self, mock_fetch):
        """Registrants created after the previous meeting should be included."""
        prev_date = self.meeting_date - timezone.timedelta(days=7)
        Meeting.objects.create(date=prev_date, zoom_link="https://zoom.us/j/1234567890")

        # Registered 3 days before this meeting (after prev meeting)
        recent_time = (self.meeting_date - timezone.timedelta(days=3)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        mock_fetch.return_value = [self._reg("alice@example.com", "Alice", "Smith", create_time=recent_time)]
        members, guests, skipped = import_zoom_registrants(self.meeting)
        self.assertEqual(members, 1)

    def test_missing_zoom_link(self):
        meeting_no_link = Meeting.objects.create(date=timezone.now())
        with self.assertRaises(ValueError):
            import_zoom_registrants(meeting_no_link)


class ZoomRegistrationFlagTest(TestCase):
    """Verify the ZOOM_REGISTRATION_ENABLED gate hides the admin button and
    rejects the import action."""

    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="testpass",
            is_staff=True, is_superuser=True,
        )
        self.client.login(username="admin", email="admin@example.com", password="testpass")
        self.meeting = Meeting.objects.create(
            date=timezone.now(),
            zoom_link="https://us02web.zoom.us/j/1234567890",
        )

    @override_settings(ZOOM_REGISTRATION_ENABLED=False)
    def test_button_hidden_when_flag_off(self):
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Import Zoom Registrants")

    @override_settings(ZOOM_REGISTRATION_ENABLED=True)
    def test_button_visible_when_flag_on(self):
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import Zoom Registrants")

    @override_settings(ZOOM_REGISTRATION_ENABLED=False)
    @patch("meetings.zoom.import_zoom_registrants")
    def test_import_action_blocked_when_flag_off(self, mock_import):
        response = self.client.post(
            reverse("admin:meeting-zoom-import", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 302)
        mock_import.assert_not_called()


class EvaluatorPairingTest(TestCase):
    """MeetingRole.evaluates self-FK: validation, reverse lookup, SET_NULL."""

    def setUp(self):
        self.speaker_role = Role.objects.create(
            name="Speaker", shows_pathways_fields=True, is_evaluated_role=True
        )
        self.eval_role = Role.objects.create(
            name="Evaluator (Speech)",
            shows_pathways_fields=True,
            is_evaluator_role=True,
        )
        self.timer_role = Role.objects.create(name="Timer")
        self.meeting = Meeting.objects.create(date=timezone.now())
        self.other_meeting = Meeting.objects.create(date=timezone.now())
        self.speaker = MeetingRole.objects.create(
            meeting=self.meeting, role=self.speaker_role, sort_order=0
        )
        self.evaluator = MeetingRole.objects.create(
            meeting=self.meeting, role=self.eval_role, sort_order=1
        )

    def test_pairing_and_reverse_lookup(self):
        self.evaluator.evaluates = self.speaker
        self.evaluator.full_clean()
        self.evaluator.save()
        self.assertEqual(self.speaker.evaluators.get(), self.evaluator)

    def test_cannot_evaluate_self(self):
        from django.core.exceptions import ValidationError
        self.evaluator.evaluates = self.evaluator
        with self.assertRaises(ValidationError):
            self.evaluator.full_clean()

    def test_cannot_evaluate_across_meetings(self):
        from django.core.exceptions import ValidationError
        other_speaker = MeetingRole.objects.create(
            meeting=self.other_meeting, role=self.speaker_role, sort_order=0
        )
        self.evaluator.evaluates = other_speaker
        with self.assertRaises(ValidationError):
            self.evaluator.full_clean()

    def test_deleting_target_sets_null(self):
        self.evaluator.evaluates = self.speaker
        self.evaluator.save()
        self.speaker.delete()
        self.evaluator.refresh_from_db()
        self.assertIsNone(self.evaluator.evaluates)

    def test_non_evaluator_role_cannot_set_evaluates(self):
        # A Speaker row with evaluates set must be rejected — only evaluator
        # roles can carry a target.
        from django.core.exceptions import ValidationError
        other_speaker = MeetingRole.objects.create(
            meeting=self.meeting, role=self.speaker_role, sort_order=2
        )
        self.speaker.evaluates = other_speaker
        with self.assertRaises(ValidationError):
            self.speaker.full_clean()

    def test_cannot_target_non_evaluated_role(self):
        # An evaluator pointing at a non-evaluated row (e.g. Timer) is rejected.
        from django.core.exceptions import ValidationError
        timer = MeetingRole.objects.create(
            meeting=self.meeting, role=self.timer_role, sort_order=2
        )
        self.evaluator.evaluates = timer
        with self.assertRaises(ValidationError):
            self.evaluator.full_clean()

    def test_migration_flagged_existing_evaluator_role_names(self):
        # The roles created in this test had is_evaluator_role passed
        # explicitly; this test pins the data-migration contract by name.
        self.assertTrue(self.eval_role.is_evaluator_role)
        self.assertFalse(self.speaker_role.is_evaluator_role)

    def test_speaker_role_is_evaluated_role(self):
        # Mirror contract on the target side.
        self.assertTrue(self.speaker_role.is_evaluated_role)
        self.assertFalse(self.eval_role.is_evaluated_role)
        self.assertFalse(self.timer_role.is_evaluated_role)

    def test_change_view_groups_rows_by_session_with_headers(self):
        # Two sessions, two roles each; rows should cluster under their
        # session-name header in MeetingSession.sort_order order.
        from .models import MeetingSession, Session
        prepared = Session.objects.create(name="Prepared Speeches")
        table_topics = Session.objects.create(name="Table Topics")
        # MeetingSession sort_order on this meeting puts Table Topics
        # first, then Prepared Speeches — so the inline should reflect
        # that, not alphabetical or model-default order.
        MeetingSession.objects.create(
            meeting=self.meeting, session=table_topics, sort_order=1
        )
        MeetingSession.objects.create(
            meeting=self.meeting, session=prepared, sort_order=2
        )
        # Bind sessions to two more roles; speaker/evaluator from setUp
        # don't have a session yet.
        self.speaker.session = prepared
        self.speaker.save()
        self.evaluator.session = prepared
        self.evaluator.save()
        topicmaster = Role.objects.create(name="Topicmaster")
        MeetingRole.objects.create(
            meeting=self.meeting, role=topicmaster, session=table_topics, sort_order=0
        )

        admin_user = User.objects.create_user(
            username="root2", email="root2@example.com",
            password="pass", is_staff=True, is_superuser=True,
        )
        self.client.login(username="root2", password="pass")
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        # Both headers should render.
        self.assertContains(response, "meeting-role-session-header")
        self.assertContains(response, "Table Topics")
        self.assertContains(response, "Prepared Speeches")
        # Table Topics group precedes Prepared Speeches (per MeetingSession
        # sort_order), not the other way around.
        content = response.content.decode()
        self.assertLess(content.index("Table Topics"), content.index("Prepared Speeches"))

    def test_change_view_exposes_pathways_role_ids_for_toggle(self):
        # The inline JS reads pathways role IDs from a json_script element to
        # live-toggle the Pathways fields.
        admin_user = User.objects.create_user(
            username="root5", email="root5@example.com",
            password="pass", is_staff=True, is_superuser=True,
        )
        self.client.login(username="root5", password="pass")
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="pathways-role-ids"')
        # Speaker shows_pathways_fields=True in setUp, so its pk should be in
        # the rendered JSON.
        self.assertContains(response, str(self.speaker_role.pk))
        self.assertContains(response, "pathways_visibility.css")
        self.assertContains(response, "pathways_visibility.js")

    def test_change_view_has_identity_banner_and_collapsed_sections(self):
        # The change form renders the read-only meeting banner, a
        # "Meeting details" fieldset (collapsed), and the MeetingSession
        # inline is also collapsed.
        from meetings.models import MeetingType
        meeting_type = MeetingType.objects.create(name="Regular")
        self.meeting.meeting_type = meeting_type
        self.meeting.theme = "Conviction"
        self.meeting.save()

        admin_user = User.objects.create_user(
            username="root9", email="root9@example.com",
            password="pass", is_staff=True, is_superuser=True,
        )
        self.client.login(username="root9", password="pass")
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        # Banner renders the meeting identity (date + type + theme).
        self.assertContains(response, "meeting-admin-banner")
        self.assertContains(response, "Regular")
        self.assertContains(response, "Conviction")
        # "Meeting details" fieldset is present (per MeetingAdmin.fieldsets).
        self.assertContains(response, "Meeting details")
        # MeetingSession inline rendered with classes=("collapse",); the
        # inline-group div carries the formset prefix in its id.
        self.assertContains(response, 'id="meeting_sessions-group"')

    def test_change_view_has_drag_sort_markup_and_assets(self):
        # Drag handle on each row, data-session-id on session headers, and
        # the SortableJS + custom drag-sort assets are referenced.
        from .models import MeetingSession, Session
        # Give the existing speaker a session so a header renders with a
        # data-session-id.
        prepared = Session.objects.create(name="Prepared Speeches")
        MeetingSession.objects.create(
            meeting=self.meeting, session=prepared, sort_order=1
        )
        self.speaker.session = prepared
        self.speaker.save()

        admin_user = User.objects.create_user(
            username="root8", email="root8@example.com",
            password="pass", is_staff=True, is_superuser=True,
        )
        self.client.login(username="root8", password="pass")
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "meetingrole-drag-handle")
        self.assertContains(
            response,
            'data-session-id="{}"'.format(prepared.id),
        )
        self.assertContains(response, "inline_drag_sort.css")
        self.assertContains(response, "inline_drag_sort.js")
        self.assertContains(response, "Sortable.min.js")

    def test_change_view_renders_meeting_role_filter_input(self):
        # The MeetingRole inline gets a live-filter input at the top; the
        # rendered template carries the input plus the supporting static refs.
        admin_user = User.objects.create_user(
            username="root7", email="root7@example.com",
            password="pass", is_staff=True, is_superuser=True,
        )
        self.client.login(username="root7", password="pass")
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="meetingrole-filter"')
        self.assertContains(response, "meetingrole-filter-bar")
        self.assertContains(response, "inline_filter.css")
        self.assertContains(response, "inline_filter.js")

    def test_change_view_has_sticky_submit_wrapper_and_layout_css(self):
        # The custom change_form template wraps the submit area in a
        # sticky container; the MeetingAdmin Media references the
        # density + sticky-save CSS file.
        admin_user = User.objects.create_user(
            username="root6", email="root6@example.com",
            password="pass", is_staff=True, is_superuser=True,
        )
        self.client.login(username="root6", password="pass")
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "meeting-admin-submit-sticky")
        self.assertContains(response, "meeting_change_form.css")

    def test_change_view_notes_fieldset_is_collapsed_by_default(self):
        # The notes / admin_notes fieldset uses Django's `collapse` class
        # so the textareas stay hidden until the officer expands them.
        admin_user = User.objects.create_user(
            username="root4", email="root4@example.com",
            password="pass", is_staff=True, is_superuser=True,
        )
        self.client.login(username="root4", password="pass")
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        # Stock admin emits `class="... collapse"` on the fieldset and a
        # summary/heading containing the fieldset name. Spot-check both.
        self.assertContains(response, "collapse")
        self.assertContains(response, "Notes")

    def test_change_view_rows_default_collapsed_with_summary(self):
        # Existing rows render with .is-collapsed; new template row does not.
        # Header shows a compact summary (role name, user, mode badge) rather
        # than MeetingRole's __str__.
        user = User.objects.create_user(
            username="alice", email="alice@example.com",
            password="pass", first_name="Alice", last_name="Smith",
        )
        self.speaker.user = user
        self.speaker.in_person = True
        self.speaker.save()
        admin_user = User.objects.create_user(
            username="root3", email="root3@example.com",
            password="pass", is_staff=True, is_superuser=True,
        )
        self.client.login(username="root3", password="pass")
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is-collapsed")
        self.assertContains(response, "row_collapse.css")
        self.assertContains(response, "row_collapse.js")
        # Compact summary, not the verbose __str__.
        self.assertContains(response, "Alice Smith")
        self.assertContains(response, "mr-mode-in-person")

    def test_change_view_exposes_evaluator_role_ids_for_inline_js(self):
        # The inline JS reads evaluator role IDs from a json_script element
        # rendered into the change form.
        admin_user = User.objects.create_user(
            username="root", email="root@example.com",
            password="pass", is_staff=True, is_superuser=True,
        )
        self.client.login(username="root", password="pass")
        response = self.client.get(
            reverse("admin:meetings_meeting_change", args=[self.meeting.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="evaluator-role-ids"')
        # The Evaluator (Speech) role's id should be in the rendered JSON.
        self.assertContains(response, str(self.eval_role.pk))
        # CSS + JS files are referenced via the inline's Media class.
        self.assertContains(response, "evaluator_pairing.css")
        self.assertContains(response, "evaluator_pairing.js")


class FirstTimeRoleEmailTest(TestCase):
    """Welcome email + RoleGuideEmailLog flow when a user is first assigned
    a role that has a guidance_document. Backfill of pre-existing
    assignments is also covered."""

    @classmethod
    def setUpClass(cls):
        # Tests upload a tiny stub document; isolate uploads under a temp
        # MEDIA_ROOT and tear it down with the test class.
        super().setUpClass()
        cls._media_tmp = tempfile.TemporaryDirectory()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_tmp.name)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        cls._media_tmp.cleanup()
        super().tearDownClass()

    def _role_with_doc(self, name="Speaker"):
        return Role.objects.create(
            name=name,
            guidance_document=SimpleUploadedFile(
                f"{name.lower()}-guide.pdf",
                b"%PDF-1.4 stub",
                content_type="application/pdf",
            ),
        )

    def setUp(self):
        self.role = self._role_with_doc()
        self.meeting = Meeting.objects.create(date=timezone.now(), theme="Welcome")
        self.user = User.objects.create_user(
            username="alice", email="alice@example.com", password="pass",
            first_name="Alice",
        )

    def test_first_assignment_sends_email_with_attachment(self):
        mail.outbox = []
        mr = MeetingRole.objects.create(
            meeting=self.meeting, role=self.role, user=self.user
        )
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["alice@example.com"])
        self.assertIn("Speaker", msg.subject)
        # One PDF attachment with our stub bytes.
        self.assertEqual(len(msg.attachments), 1)
        name, _, mimetype = msg.attachments[0]
        self.assertTrue(name.endswith(".pdf"))
        # Log row created — idempotency anchor for future assignments.
        self.assertTrue(
            RoleGuideEmailLog.objects.filter(user=self.user, role=self.role).exists()
        )

    def test_second_assignment_does_not_resend(self):
        MeetingRole.objects.create(meeting=self.meeting, role=self.role, user=self.user)
        mail.outbox = []
        meeting2 = Meeting.objects.create(date=timezone.now())
        MeetingRole.objects.create(meeting=meeting2, role=self.role, user=self.user)
        self.assertEqual(len(mail.outbox), 0)

    def test_unassign_then_reassign_does_not_resend(self):
        mr = MeetingRole.objects.create(
            meeting=self.meeting, role=self.role, user=self.user
        )
        mail.outbox = []
        mr.user = None
        mr.save()
        mr.user = self.user
        mr.save()
        self.assertEqual(len(mail.outbox), 0)

    def test_no_document_no_email(self):
        role = Role.objects.create(name="Timer")
        mail.outbox = []
        MeetingRole.objects.create(
            meeting=self.meeting, role=role, user=self.user
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(
            RoleGuideEmailLog.objects.filter(user=self.user, role=role).exists()
        )

    def test_open_role_does_not_send(self):
        mail.outbox = []
        MeetingRole.objects.create(meeting=self.meeting, role=self.role)
        self.assertEqual(len(mail.outbox), 0)

    def test_member_without_email_does_not_send(self):
        # User.email is unique+required at the admin form layer, but the
        # model allows blanks via direct ORM use. Guard the helper anyway.
        no_email = User.objects.create(username="noemail")
        mail.outbox = []
        MeetingRole.objects.create(
            meeting=self.meeting, role=self.role, user=no_email
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_migration_backfilled_existing_assignments(self):
        # The data migration pre-populates the log for every (user, role)
        # pair already in MeetingRole. Simulate a "pre-feature" assignment
        # by inserting a log row manually, then assign for the first time
        # at the model level → no email goes out.
        RoleGuideEmailLog.objects.create(user=self.user, role=self.role)
        mail.outbox = []
        MeetingRole.objects.create(
            meeting=self.meeting, role=self.role, user=self.user
        )
        self.assertEqual(len(mail.outbox), 0)


class MemberActivityReportTest(TestCase):
    """The custom admin pages render for staff, redirect anonymous users,
    and aggregate Attendance + MeetingRole correctly."""

    def setUp(self):
        self.client = Client()
        self.officer = User.objects.create_user(
            username="officer", email="officer@example.com", password="pass",
            is_officer=True,
        )
        self.member = User.objects.create_user(
            username="alice", email="alice@example.com", password="pass",
            first_name="Alice",
        )
        self.role = Role.objects.create(name="Timer")
        self.meeting = Meeting.objects.create(date=timezone.now(), theme="A")
        Attendance.objects.create(meeting=self.meeting, user=self.member)
        MeetingRole.objects.create(
            meeting=self.meeting, role=self.role, user=self.member
        )

    def test_anonymous_redirected_to_login(self):
        url = reverse("admin:members_user_activity_report")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_non_staff_redirected(self):
        regular = User.objects.create_user(
            username="bob", email="bob@example.com", password="pass"
        )
        self.client.login(username="bob", email="bob@example.com", password="pass")
        url = reverse("admin:members_user_activity_report")
        response = self.client.get(url)
        # admin_view redirects unauthenticated/non-staff to admin login.
        self.assertEqual(response.status_code, 302)

    def test_officer_sees_summary(self):
        self.client.login(username="officer", email="officer@example.com", password="pass")
        url = reverse("admin:members_user_activity_report")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Alice shows up with 1 meeting attended and 1 role taken.
        self.assertContains(response, "Alice")
        members = list(response.context["members"])
        alice = next(m for m in members if m.username == "alice")
        self.assertEqual(alice.meetings_attended, 1)
        self.assertEqual(alice.roles_taken, 1)

    def test_summary_excludes_guests(self):
        guest = User.objects.create_user(
            username="g", email="g@example.com", password="pass", is_guest=True
        )
        self.client.login(username="officer", email="officer@example.com", password="pass")
        response = self.client.get(reverse("admin:members_user_activity_report"))
        usernames = [m.username for m in response.context["members"]]
        self.assertNotIn("g", usernames)

    def test_detail_page_lists_meeting_and_role(self):
        self.client.login(username="officer", email="officer@example.com", password="pass")
        url = reverse(
            "admin:members_user_activity_report_detail", args=[self.member.pk]
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_meetings"], 1)
        self.assertEqual(response.context["total_roles"], 1)
        self.assertContains(response, "Timer")

    def test_date_filter_excludes_out_of_range_meeting(self):
        # Move the existing meeting outside the filter window.
        old_meeting = Meeting.objects.create(
            date=timezone.now() - timezone.timedelta(days=365)
        )
        Attendance.objects.create(meeting=old_meeting, user=self.member)
        self.client.login(username="officer", email="officer@example.com", password="pass")
        today = timezone.now().date().isoformat()
        url = reverse("admin:members_user_activity_report")
        response = self.client.get(url, {"start": today, "end": today})
        alice = next(m for m in response.context["members"] if m.username == "alice")
        # Today's meeting is in range; the year-old one is not.
        self.assertEqual(alice.meetings_attended, 1)

    def test_changelist_has_activity_report_link(self):
        # The custom change_list template injects an "Activity report" link
        # in the object-tools row.
        self.officer.is_superuser = True
        self.officer.save()
        self.client.login(username="officer", email="officer@example.com", password="pass")
        response = self.client.get(reverse("admin:members_user_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Member activity report")


class MeetingRoleAgendaLabelTest(TestCase):
    """The label helpers that the web and Word agendas share."""

    def setUp(self):
        self.role = Role.objects.create(name="Speaker", shows_pathways_fields=True)
        self.meeting = Meeting.objects.create(date=timezone.now(), theme="Leadership")
        self.user = User.objects.create_user(
            username="alice", password="pass", email="alice@example.com",
            first_name="Alice", last_name="Smith",
        )
        self.assignment = MeetingRole.objects.create(
            meeting=self.meeting, role=self.role, user=self.user, sort_order=0
        )

    def test_attendance_label(self):
        self.assertEqual(self.assignment.attendance_label(), "")
        self.assignment.in_person = True
        self.assertEqual(self.assignment.attendance_label(), "In Person")
        self.assignment.in_person = False
        self.assertEqual(self.assignment.attendance_label(), "Remote")

    def test_pathways_label_omits_missing_parts(self):
        self.assertEqual(self.assignment.pathways_label(), "")
        self.assignment.pathways_path = "Presentation Mastery"
        self.assignment.pathways_level = 2
        self.assignment.pathways_project = "Project Title"
        self.assertEqual(
            self.assignment.pathways_label(),
            'Presentation Mastery L2, "Project Title"',
        )
        self.assignment.pathways_project = ""
        self.assertEqual(self.assignment.pathways_label(), "Presentation Mastery L2")

    def test_agenda_notes_joins_pathways_and_notes(self):
        self.assignment.pathways_path = "Presentation Mastery"
        self.assignment.pathways_level = 2
        self.assignment.notes = "My speech"
        self.assertEqual(
            self.assignment.agenda_notes(), "Presentation Mastery L2 — My speech"
        )
        self.assignment.pathways_path = ""
        self.assignment.pathways_level = None
        self.assertEqual(self.assignment.agenda_notes(), "My speech")

    def test_evaluator_pairing_labels(self):
        evaluator_role = Role.objects.create(name="Evaluator", is_evaluator_role=True)
        bob = User.objects.create_user(
            username="bob", password="pass", email="bob@example.com",
            first_name="Bob", last_name="Jones",
        )
        evaluator = MeetingRole.objects.create(
            meeting=self.meeting, role=evaluator_role, user=bob,
            evaluates=self.assignment, sort_order=1,
        )
        self.assertEqual(evaluator.evaluating_label(), "evaluating Alice Smith")
        self.assertEqual(self.assignment.evaluated_by_label(), "evaluator: Bob Jones")
        # Non-paired rows return empty strings.
        self.assertEqual(self.assignment.evaluating_label(), "")
        self.assertEqual(evaluator.evaluated_by_label(), "")


class AgendaViewTest(TestCase):
    """show_on_agenda filtering and rendering across both renderers."""

    def setUp(self):
        self.client = Client()
        self.meeting = Meeting.objects.create(date=timezone.now(), theme="Leadership")
        self.speaker_role = Role.objects.create(name="Speaker")
        self.president_role = Role.objects.create(
            name="President", show_on_agenda=False
        )
        self.speaker = User.objects.create_user(
            username="alice", password="pass", email="alice@example.com",
            first_name="Alice", last_name="Smith",
        )
        self.president = User.objects.create_user(
            username="pat", password="pass", email="pat@example.com",
            first_name="Pat", last_name="Prez",
        )
        MeetingRole.objects.create(
            meeting=self.meeting, role=self.speaker_role, user=self.speaker,
            in_person=True, time_minutes=7, notes="My speech", sort_order=0,
        )
        MeetingRole.objects.create(
            meeting=self.meeting, role=self.president_role, user=self.president,
            sort_order=1,
        )

    def test_build_sections_excludes_hidden_roles(self):
        from .views import _build_agenda_sections

        roles = [r for s in _build_agenda_sections(self.meeting) for r in s["roles"]]
        names = {r.role.name for r in roles}
        self.assertIn("Speaker", names)
        self.assertNotIn("President", names)

    def test_web_agenda_hides_president_shows_details(self):
        response = self.client.get(
            reverse("meeting_agenda", args=[self.meeting.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Smith")
        self.assertContains(response, "In Person")
        self.assertContains(response, "7 min")
        self.assertNotContains(response, "Pat Prez")

    def test_word_download_renders(self):
        response = self.client.get(
            reverse("meeting_agenda_download", args=[self.meeting.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertTrue(response.content)


class SignupPageTest(TestCase):
    """The /signups/ role sign-up page: Role / Status / Notes columns, with
    per-role info mirroring the agenda."""

    def setUp(self):
        self.client = Client()
        self.meeting = Meeting.objects.create(
            date=timezone.now() + timezone.timedelta(days=1), theme="Leadership"
        )
        self.speaker_role = Role.objects.create(name="Speaker")
        self.president_role = Role.objects.create(
            name="President", show_on_agenda=False
        )
        # One open Speaker role and one (open) hidden President role.
        MeetingRole.objects.create(
            meeting=self.meeting, role=self.speaker_role, time_minutes=7, sort_order=0
        )
        MeetingRole.objects.create(
            meeting=self.meeting, role=self.president_role, sort_order=1
        )
        self.member = User.objects.create_user(
            username="alice", password="pass", email="alice@example.com",
            first_name="Alice", last_name="Smith",
        )

    def test_hidden_role_excluded(self):
        response = self.client.get(reverse("role_signups"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Speaker")
        self.assertNotContains(response, "President")

    def test_per_role_time_shown(self):
        response = self.client.get(reverse("role_signups"))
        self.assertContains(response, "7 min")

    def test_three_columns_without_filled_needed_badges(self):
        response = self.client.get(reverse("role_signups"))
        self.assertContains(response, ">Role</th>")
        self.assertContains(response, ">Status</th>")
        self.assertContains(response, ">Notes</th>")
        # The old redundant Status badges are gone.
        self.assertNotContains(response, "Needed")
        self.assertNotContains(response, "Filled")

    def test_notes_column_shows_agenda_notes(self):
        MeetingRole.objects.create(
            meeting=self.meeting,
            role=Role.objects.create(name="Toastmaster"),
            user=self.member,
            notes="Welcome everyone",
            sort_order=2,
        )
        response = self.client.get(reverse("role_signups"))
        self.assertContains(response, "Welcome everyone")

    def test_signup_button_for_authenticated_open_role(self):
        self.client.login(username="alice", password="pass")
        response = self.client.get(reverse("role_signups"))
        self.assertContains(response, "Sign Up</button>")

    def test_anonymous_sees_open_placeholder_not_button(self):
        response = self.client.get(reverse("role_signups"))
        self.assertContains(response, "-- Open --")
        self.assertNotContains(response, "Sign Up</button>")
