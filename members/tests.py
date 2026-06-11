from datetime import timedelta

from django.contrib.auth.models import Group
from django.core import mail
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from meetings.models import Meeting, MeetingRole, Role

from django.contrib.auth import authenticate

from .admin import CustomUserCreationForm, make_officer, remove_officer
from .models import User
from .emails import send_welcome_email
from .signals import OFFICERS_GROUP_NAME
from .tokens import make_email_change_token, make_login_token


class EmailBackendTest(TestCase):
    """Members authenticate by email; usernames stay internal but still work
    for the admin via the ModelBackend fallback."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="auto.generated", email="member@example.com", password="secret"
        )

    def test_login_by_email(self):
        self.assertEqual(
            authenticate(username="member@example.com", password="secret"), self.user
        )

    def test_login_by_email_is_case_insensitive(self):
        self.assertEqual(
            authenticate(username="Member@Example.COM", password="secret"), self.user
        )

    def test_wrong_password_rejected(self):
        self.assertIsNone(
            authenticate(username="member@example.com", password="nope")
        )

    def test_unknown_email_rejected(self):
        self.assertIsNone(
            authenticate(username="ghost@example.com", password="secret")
        )

    def test_username_login_still_works_for_admin(self):
        # ModelBackend fallback keeps Django admin's username login functional.
        self.assertEqual(
            authenticate(username="auto.generated", password="secret"), self.user
        )

    def test_inactive_user_rejected(self):
        self.user.is_active = False
        self.user.save()
        self.assertIsNone(
            authenticate(username="member@example.com", password="secret")
        )


class LoginPageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="auto.gen", email="member@example.com", password="secret"
        )

    def test_password_login_by_email(self):
        resp = self.client.post(
            reverse("login"),
            {"username": "member@example.com", "password": "secret"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)


class MagicLinkTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="auto.gen", email="member@example.com", password="secret",
            first_name="Mem",
        )

    def test_request_sends_link_for_known_email(self):
        resp = self.client.post(
            reverse("magic_link_request"), {"email": "member@example.com"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/magic-link/", mail.outbox[0].body)

    def test_request_unknown_email_sends_nothing_but_same_page(self):
        # No user enumeration: identical response, no email sent.
        resp = self.client.post(
            reverse("magic_link_request"), {"email": "ghost@example.com"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_valid_link_logs_in(self):
        token = make_login_token(self.user)
        resp = self.client.get(reverse("magic_link_login", args=[token]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_tampered_token_rejected(self):
        resp = self.client.get(reverse("magic_link_login", args=["not-a-token"]))
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(MAGIC_LINK_MAX_AGE=-1)
    def test_expired_link_rejected(self):
        token = make_login_token(self.user)
        resp = self.client.get(reverse("magic_link_login", args=[token]))
        self.assertEqual(resp.status_code, 400)

    def test_password_change_invalidates_outstanding_link(self):
        token = make_login_token(self.user)
        self.user.set_password("changed")
        self.user.save()
        resp = self.client.get(reverse("magic_link_login", args=[token]))
        self.assertEqual(resp.status_code, 400)


class AccountPageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="auto.gen", email="member@example.com", password="x",
            first_name="Mem", last_name="Ber",
        )
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("account"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_get_renders(self):
        self.assertEqual(self.client.get(reverse("account")).status_code, 200)

    def test_update_name(self):
        resp = self.client.post(
            reverse("account_profile"), {"first_name": "New", "last_name": "Name"}
        )
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("New", "Name"))

    def test_set_password_keeps_session(self):
        resp = self.client.post(
            reverse("account_password"),
            {"new_password1": "sk8board-ninja-42", "new_password2": "sk8board-ninja-42"},
        )
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("sk8board-ninja-42"))
        # Still authenticated (session hash was refreshed).
        self.assertEqual(self.client.get(reverse("account")).status_code, 200)

    def test_email_change_request_sends_link_without_changing_email(self):
        resp = self.client.post(
            reverse("account_email"), {"new_email": "new@example.com"}
        )
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "member@example.com")  # unchanged yet
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new@example.com"])

    def test_email_change_rejects_taken_address(self):
        User.objects.create_user(
            username="other", email="taken@example.com", password="x"
        )
        resp = self.client.post(
            reverse("account_email"), {"new_email": "taken@example.com"}
        )
        self.assertEqual(resp.status_code, 200)  # re-rendered with error
        self.assertEqual(len(mail.outbox), 0)

    def test_email_confirm_applies_change(self):
        token = make_email_change_token(self.user, "new@example.com")
        resp = self.client.get(reverse("account_email_confirm", args=[token]))
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")

    def test_email_confirm_rejects_other_users_token(self):
        other = User.objects.create_user(
            username="other", email="other@example.com", password="x"
        )
        token = make_email_change_token(other, "hijack@example.com")
        resp = self.client.get(reverse("account_email_confirm", args=[token]))
        self.assertEqual(resp.status_code, 302)
        other.refresh_from_db()
        self.assertEqual(other.email, "other@example.com")  # unchanged

    @override_settings(EMAIL_CHANGE_MAX_AGE=-1)
    def test_email_confirm_rejects_expired_token(self):
        token = make_email_change_token(self.user, "new@example.com")
        self.client.get(reverse("account_email_confirm", args=[token]))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "member@example.com")

    def test_email_confirm_rejects_now_taken_address(self):
        token = make_email_change_token(self.user, "new@example.com")
        # Someone else grabs the address before the link is clicked.
        User.objects.create_user(
            username="other", email="new@example.com", password="x"
        )
        self.client.get(reverse("account_email_confirm", args=[token]))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "member@example.com")


class WelcomeEmailTest(TestCase):
    def test_welcome_email_points_to_login(self):
        user = User.objects.create_user(
            username="auto.gen", email="member@example.com", password="x",
            first_name="Mem",
        )
        sent = send_welcome_email(user)
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn(reverse("login"), body)
        self.assertIn("member@example.com", body)


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

    def test_officers_group_manages_users_except_delete(self):
        group = Group.objects.get(name=OFFICERS_GROUP_NAME)
        codenames = set(group.permissions.values_list("codename", flat=True))
        # Officers can add/change/view members...
        for codename in ("add_user", "change_user", "view_user"):
            self.assertIn(codename, codenames)
        # ...but not delete users, nor touch groups/permissions.
        self.assertNotIn("delete_user", codenames)
        self.assertNotIn("change_group", codenames)
        self.assertNotIn("change_permission", codenames)


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


class ActivityReportTest(TestCase):
    """Summary filter, detail breakdown, and role-invite behavior."""

    def setUp(self):
        self.staff = User.objects.create_superuser(
            username="boss", email="boss@example.com", password="pw")
        self.client.force_login(self.staff)

        self.tm = Role.objects.create(name="Toastmaster")
        self.timer = Role.objects.create(name="Timer")
        # President is not sign-up-able; it must never appear in the breakdown
        # or be invitable.
        self.president = Role.objects.create(name="President", show_on_agenda=False)

        self.alice = User.objects.create_user(
            username="alice", email="alice@example.com", password="pw",
            first_name="Alice", last_name="Adams")
        self.bob = User.objects.create_user(
            username="bob", email="bob@example.com", password="pw",
            first_name="Bob", last_name="Brown")

        # A past meeting where Alice was Toastmaster.
        self.past = Meeting.objects.create(
            date=timezone.now() - timedelta(days=10))
        MeetingRole.objects.create(meeting=self.past, role=self.tm,
                                   user=self.alice)

    def _upcoming_with_open_tm(self):
        m = Meeting.objects.create(date=timezone.now() + timedelta(days=5))
        MeetingRole.objects.create(meeting=m, role=self.tm, user=None)
        return m

    # --- summary role filter ---

    def test_taken_filter_includes_only_role_holders(self):
        url = reverse("admin:members_user_activity_report")
        members = list(self.client.get(
            url, {"role": self.tm.pk, "taken": "yes"}).context["members"])
        self.assertIn(self.alice, members)
        self.assertNotIn(self.bob, members)

    def test_not_taken_filter_excludes_role_holders(self):
        url = reverse("admin:members_user_activity_report")
        members = list(self.client.get(
            url, {"role": self.tm.pk, "taken": "no"}).context["members"])
        self.assertNotIn(self.alice, members)
        self.assertIn(self.bob, members)

    def test_filter_honors_date_range(self):
        # Alice's role is 10 days ago; a window starting 5 days ago excludes it,
        # so she counts as "not taken" in that range.
        url = reverse("admin:members_user_activity_report")
        start = (timezone.now() - timedelta(days=5)).date().isoformat()
        members = list(self.client.get(
            url, {"role": self.tm.pk, "taken": "no", "start": start}
        ).context["members"])
        self.assertIn(self.alice, members)

    # --- detail breakdown ---

    def test_detail_lists_all_signup_roles_with_counts(self):
        url = reverse("admin:members_user_activity_report_detail",
                      args=[self.alice.pk])
        breakdown = {r["role"].name: r
                     for r in self.client.get(url).context["role_breakdown"]}
        self.assertEqual(breakdown["Toastmaster"]["count"], 1)
        self.assertIsNotNone(breakdown["Toastmaster"]["last_taken"])
        # Timer never taken, but still listed with a zero count.
        self.assertEqual(breakdown["Timer"]["count"], 0)
        self.assertIsNone(breakdown["Timer"]["last_taken"])
        # President is off-agenda -> not in the breakdown.
        self.assertNotIn("President", breakdown)

    # --- invite form (checkboxes + single button; sending happens on the
    #     shared review page) ---

    def test_invite_form_posts_to_review_when_upcoming(self):
        self._upcoming_with_open_tm()
        url = reverse("admin:members_user_activity_report_detail", args=[self.bob.pk])
        resp = self.client.get(url)
        html = resp.content.decode()
        self.assertTrue(resp.context["upcoming_exists"])
        # Form targets the review page with the invite workflow.
        self.assertIn(f'action="{reverse("email_review")}"', html)
        self.assertIn('name="workflow" value="invite"', html)
        # Each sign-up-able role gets its own (enabled) checkbox.
        self.assertIn(f'name="role" value="{self.tm.pk}"', html)
        self.assertIn(f'name="role" value="{self.timer.pk}"', html)

    def test_invite_disabled_without_upcoming(self):
        url = reverse("admin:members_user_activity_report_detail", args=[self.bob.pk])
        resp = self.client.get(url)
        self.assertFalse(resp.context["upcoming_exists"])
        self.assertIn("disabled", resp.content.decode())


class OfficerUserAdminGuardTest(TestCase):
    """Officers can manage members, but the admin blocks every privilege-
    escalation path: privilege fields, officer promotion, and CSV import."""

    def setUp(self):
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        from .admin import CustomUserAdmin

        self.admin = CustomUserAdmin(User, AdminSite())
        self.rf = RequestFactory()
        self.officer = User.objects.create_user(
            "off", "off@example.com", "pw", is_officer=True)
        self.superuser = User.objects.create_superuser(
            "root", "root@example.com", "pw")
        self.target = User.objects.create_user("m", "m@example.com", "pw")

    def _req(self, user):
        req = self.rf.get("/")
        req.user = user
        return req

    @staticmethod
    def _fields(fieldsets):
        return {f for _, opts in fieldsets for f in opts["fields"]}

    def test_officer_change_form_hides_privilege_fields(self):
        fields = self._fields(self.admin.get_fieldsets(self._req(self.officer), self.target))
        for f in ("is_staff", "is_superuser", "is_officer", "groups", "user_permissions"):
            self.assertNotIn(f, fields)
        # but can still manage member data, including activation
        for f in ("is_active", "is_guest", "email", "mentor"):
            self.assertIn(f, fields)

    def test_superuser_change_form_keeps_privilege_fields(self):
        fields = self._fields(self.admin.get_fieldsets(self._req(self.superuser), self.target))
        self.assertIn("is_superuser", fields)
        self.assertIn("is_officer", fields)

    def test_officer_cannot_promote_officers(self):
        actions = self.admin.get_actions(self._req(self.officer))
        self.assertNotIn("make_officer", actions)
        self.assertNotIn("remove_officer", actions)
        self.assertIn("make_guest", actions)  # roster actions still available

    def test_superuser_can_promote_officers(self):
        self.assertIn("make_officer", self.admin.get_actions(self._req(self.superuser)))

    def test_csv_import_is_superuser_only(self):
        self.assertFalse(self.admin.has_import_permission(self._req(self.officer)))
        self.assertTrue(self.admin.has_import_permission(self._req(self.superuser)))
