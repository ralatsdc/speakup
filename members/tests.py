from django.test import TestCase

from .models import User


class UserModelTest(TestCase):
    def test_status_label_member(self):
        user = User.objects.create_user(username="member", password="pass")
        self.assertEqual(user.status_label, "Member")

    def test_status_label_guest(self):
        user = User.objects.create_user(username="guest", password="pass", is_guest=True)
        self.assertEqual(user.status_label, "Guest")

    def test_str_with_first_name(self):
        user = User.objects.create_user(
            username="jdoe", password="pass", first_name="John"
        )
        self.assertEqual(str(user), "John")

    def test_str_without_first_name(self):
        user = User.objects.create_user(username="jdoe", password="pass")
        self.assertEqual(str(user), "jdoe")
