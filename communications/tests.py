from unittest.mock import patch

from django.test import TestCase

from members.models import User
from .models import Announcement


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

    @patch("communications.utils.send_mass_mail")
    def test_send_to_all(self, mock_send):
        announcement = Announcement.objects.create(
            subject="Hello", body="Test", audience="all"
        )
        announcement.send()
        mock_send.assert_called_once()
        messages = mock_send.call_args[0][0]
        self.assertEqual(len(messages), 3)

    @patch("communications.utils.send_mass_mail")
    def test_send_to_officers(self, mock_send):
        announcement = Announcement.objects.create(
            subject="Officers only", body="Test", audience="officers"
        )
        announcement.send()
        messages = mock_send.call_args[0][0]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][3], ["officer@example.com"])

    @patch("communications.utils.send_mass_mail")
    def test_send_to_guests(self, mock_send):
        announcement = Announcement.objects.create(
            subject="Guests only", body="Test", audience="guests"
        )
        announcement.send()
        messages = mock_send.call_args[0][0]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][3], ["guest@example.com"])
