from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.test import TestCase

from .admin import CustomUserCreationForm, make_officer, remove_officer
from .models import User
from .signals import OFFICERS_GROUP_NAME


class UserModelTest(TestCase):
    def test_status_label_member(self):
        user = User.objects.create_user(username="member", email="member@example.com", password="pass")
        self.assertEqual(user.status_label, "Member")

    def test_status_label_guest(self):
        user = User.objects.create_user(username="guest", email="guest@example.com", password="pass", is_guest=True)
        self.assertEqual(user.status_label, "Guest")

    def test_str_with_first_name(self):
        user = User.objects.create_user(
            username="jdoe", email="jdoe@example.com", password="pass", first_name="John"
        )
        self.assertEqual(str(user), "John")

    def test_str_without_first_name(self):
        user = User.objects.create_user(username="jdoe", email="jdoe@example.com", password="pass")
        self.assertEqual(str(user), "jdoe")


class EmailUniquenessTest(TestCase):
    """Email is unique and lowercased on save."""

    def test_save_lowercases_email(self):
        user = User.objects.create_user(
            username="alice", password="pass", email="Alice@Example.COM"
        )
        user.refresh_from_db()
        self.assertEqual(user.email, "alice@example.com")

    def test_duplicate_email_raises_integrity_error(self):
        User.objects.create_user(
            username="alice", password="pass", email="alice@example.com"
        )
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username="bob", password="pass", email="alice@example.com"
            )

    def test_case_difference_duplicate_is_caught(self):
        # Save lowercases the email, so a "different" case attempt collides.
        User.objects.create_user(
            username="alice", password="pass", email="alice@example.com"
        )
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username="bob", password="pass", email="ALICE@example.com"
            )

    def test_admin_add_form_requires_email(self):
        form = CustomUserCreationForm(
            data={"username": "newuser", "password1": "x", "password2": "x"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)


class OfficersGroupSeededTest(TestCase):
    """Migration 0003 should have created the Officers group with permissions."""

    def test_officers_group_exists(self):
        self.assertTrue(Group.objects.filter(name=OFFICERS_GROUP_NAME).exists())

    def test_officers_group_has_meeting_permissions(self):
        group = Group.objects.get(name=OFFICERS_GROUP_NAME)
        codenames = set(group.permissions.values_list("codename", flat=True))
        # Spot-check a representative permission from each grouping.
        for codename in (
            "change_meeting",
            "add_meetingrole",
            "delete_attendance",
            "view_meetingtype",
            "change_announcement",
        ):
            self.assertIn(codename, codenames)

    def test_officers_group_does_not_grant_user_management(self):
        group = Group.objects.get(name=OFFICERS_GROUP_NAME)
        codenames = set(group.permissions.values_list("codename", flat=True))
        # User management stays superuser-only.
        for codename in ("add_user", "change_user", "delete_user"):
            self.assertNotIn(codename, codenames)


class OfficerSyncTest(TestCase):
    """Saving a User with is_officer=True should grant is_staff + Officers group;
    setting it back to False should reverse both — except is_staff stays on
    superusers."""

    def test_become_officer_grants_is_staff_and_group(self):
        user = User.objects.create_user(username="alice", email="alice@example.com", password="pass")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())

        user.is_officer = True
        user.save()
        user.refresh_from_db()

        self.assertTrue(user.is_staff)
        self.assertTrue(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())

    def test_un_officer_removes_is_staff_and_group(self):
        user = User.objects.create_user(
            username="bob", email="bob@example.com", password="pass", is_officer=True
        )
        user.refresh_from_db()
        self.assertTrue(user.is_staff)

        user.is_officer = False
        user.save()
        user.refresh_from_db()

        self.assertFalse(user.is_staff)
        self.assertFalse(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())

    def test_un_officer_preserves_is_staff_for_superuser(self):
        # Superusers always need is_staff, regardless of officer status.
        user = User.objects.create_user(
            username="root", email="root@example.com", password="pass",
            is_officer=True, is_superuser=True,
        )
        user.is_officer = False
        user.save()
        user.refresh_from_db()

        self.assertTrue(user.is_staff)
        self.assertFalse(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())

    def test_creating_with_is_officer_true_grants_everything(self):
        user = User.objects.create_user(
            username="carol", email="carol@example.com", password="pass", is_officer=True
        )
        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())


class _DummyModelAdmin:
    """Stand-in for ModelAdmin so admin actions can be called without a request."""

    def message_user(self, request, message, *args, **kwargs):
        pass


class OfficerBulkAdminActionTest(TestCase):
    """The make_officer / remove_officer bulk actions must fire the post_save
    signal — they iterate + save() rather than queryset.update()."""

    def test_make_officer_bulk_action_grants_is_staff_and_group(self):
        u1 = User.objects.create_user(username="u1", email="u1@example.com", password="pass")
        u2 = User.objects.create_user(username="u2", email="u2@example.com", password="pass")

        make_officer(
            _DummyModelAdmin(), None,
            User.objects.filter(pk__in=[u1.pk, u2.pk]),
        )

        for user in (u1, u2):
            user.refresh_from_db()
            self.assertTrue(user.is_officer)
            self.assertTrue(user.is_staff)
            self.assertTrue(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())

    def test_remove_officer_bulk_action_reverses_is_staff_and_group(self):
        u1 = User.objects.create_user(
            username="u1", email="u1@example.com", password="pass", is_officer=True
        )
        u2 = User.objects.create_user(
            username="u2", email="u2@example.com", password="pass", is_officer=True
        )

        remove_officer(
            _DummyModelAdmin(), None,
            User.objects.filter(pk__in=[u1.pk, u2.pk]),
        )

        for user in (u1, u2):
            user.refresh_from_db()
            self.assertFalse(user.is_officer)
            self.assertFalse(user.is_staff)
            self.assertFalse(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())
