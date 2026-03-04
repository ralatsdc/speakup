from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from members.models import User
from .models import Meeting, MeetingType, MeetingTypeItem, MeetingRole, Role, Attendance
from .services import convert_guest_attendance_to_user
from .zoom import extract_zoom_meeting_id, import_zoom_registrants


class MeetingSignalTest(TestCase):
    """Test that creating a Meeting auto-populates roles from its MeetingType."""

    def setUp(self):
        self.role_speaker = Role.objects.create(name="Speaker", is_speech_role=True)
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


class UpcomingMeetingsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="testpass")

    def test_anonymous_access(self):
        response = self.client.get(reverse("upcoming_meetings"))
        self.assertEqual(response.status_code, 200)

    def test_authenticated_access(self):
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(reverse("upcoming_meetings"))
        self.assertEqual(response.status_code, 200)


class ToggleRoleViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="member1", password="testpass")
        self.user2 = User.objects.create_user(username="member2", password="testpass")
        role = Role.objects.create(name="Timer")
        self.meeting = Meeting.objects.create(date=timezone.now())
        self.assignment = MeetingRole.objects.create(
            meeting=self.meeting, role=role, sort_order=0
        )

    def test_claim_role(self):
        self.client.login(username="member1", password="testpass")
        response = self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.user, self.user)

    def test_drop_role(self):
        self.assignment.user = self.user
        self.assignment.save()
        self.client.login(username="member1", password="testpass")
        self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.user)

    def test_cannot_take_occupied_role(self):
        self.assignment.user = self.user2
        self.assignment.save()
        self.client.login(username="member1", password="testpass")
        response = self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assertEqual(response.status_code, 403)

    def test_guest_cannot_claim_role(self):
        guest = User.objects.create_user(
            username="guest1", password="testpass", is_guest=True
        )
        self.client.login(username="guest1", password="testpass")
        response = self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.user)
        self.assertIn("Guests cannot sign up", response["HX-Trigger"])

    def test_requires_login(self):
        response = self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assertEqual(response.status_code, 302)


class CheckinKioskViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", password="testpass", is_officer=True
        )

    def test_no_meeting_shows_warning(self):
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(reverse("checkin_kiosk"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No meeting found")


class CheckinMemberViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", password="testpass", is_officer=True
        )
        self.meeting = Meeting.objects.create(date=timezone.now())

    def test_checkin_creates_attendance(self):
        self.client.login(username="testuser", password="testpass")
        self.client.post(reverse("checkin_member", args=[self.meeting.id, self.user.id]))
        self.assertTrue(Attendance.objects.filter(meeting=self.meeting, user=self.user).exists())

    def test_checkin_toggle_removes_attendance(self):
        self.client.login(username="testuser", password="testpass")
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
        linked_user = User.objects.create_user(username="linked", password="pass")
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
        self.role = Role.objects.create(name="Speaker", is_speech_role=True)
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
