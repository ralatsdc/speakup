from django.contrib.auth.models import Group
from django.test import TestCase

from .admin import make_officer, remove_officer
from .models import User
from .signals import OFFICERS_GROUP_NAME


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
        user = User.objects.create_user(username="alice", password="pass")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())

        user.is_officer = True
        user.save()
        user.refresh_from_db()

        self.assertTrue(user.is_staff)
        self.assertTrue(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())

    def test_un_officer_removes_is_staff_and_group(self):
        user = User.objects.create_user(
            username="bob", password="pass", is_officer=True
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
            username="root", password="pass",
            is_officer=True, is_superuser=True,
        )
        user.is_officer = False
        user.save()
        user.refresh_from_db()

        self.assertTrue(user.is_staff)
        self.assertFalse(user.groups.filter(name=OFFICERS_GROUP_NAME).exists())

    def test_creating_with_is_officer_true_grants_everything(self):
        user = User.objects.create_user(
            username="carol", password="pass", is_officer=True
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
        u1 = User.objects.create_user(username="u1", password="pass")
        u2 = User.objects.create_user(username="u2", password="pass")

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
            username="u1", password="pass", is_officer=True
        )
        u2 = User.objects.create_user(
            username="u2", password="pass", is_officer=True
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
