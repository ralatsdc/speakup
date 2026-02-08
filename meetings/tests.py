from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from members.models import User
from .models import Meeting, MeetingType, MeetingTypeItem, MeetingRole, Role, Attendance
from .services import convert_guest_attendance_to_user


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

    def test_requires_login(self):
        response = self.client.get(reverse("upcoming_meetings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

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

    def test_requires_login(self):
        response = self.client.post(reverse("toggle_role", args=[self.assignment.id]))
        self.assertEqual(response.status_code, 302)


class CheckinKioskViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="testpass")

    def test_no_meeting_shows_warning(self):
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(reverse("checkin_kiosk"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No meeting found")


class CheckinMemberViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="testpass")
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
            meeting=self.meeting, guest_name="Jane Doe", guest_email="jane@example.com"
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
            meeting=self.meeting, guest_name="Jane Doe", guest_email="jane@example.com"
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
            meeting=self.meeting, guest_name="No Email"
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
        count = send_meeting_feedback(self.meeting)
        self.assertEqual(count, 1)
        mock_send.assert_called_once()

    @patch("meetings.utils.send_mass_mail")
    def test_send_feedback_no_notes(self, mock_send):
        from .utils import send_meeting_feedback

        count = send_meeting_feedback(self.meeting)
        self.assertEqual(count, 0)
        mock_send.assert_called_once()
