from django.test import TestCase
from django.urls import reverse

from members.models import User


class NavbarKioskLinkTest(TestCase):
    """The 'Kiosk' nav link is shown only to officers and superusers.

    Tests hit the landing page (which extends base.html) and inspect the
    rendered HTML for the link.
    """

    LANDING_URL_NAME = "landing"
    LINK_HREF_FRAGMENT = 'href="/kiosk/"'

    def _create(self, username, **flags):
        return User.objects.create_user(
            username=username, password="testpass", **flags
        )

    def _get_landing(self):
        return self.client.get(reverse(self.LANDING_URL_NAME))

    def test_link_hidden_for_anonymous(self):
        response = self._get_landing()
        self.assertNotContains(response, self.LINK_HREF_FRAGMENT)

    def test_link_hidden_for_regular_member(self):
        self._create("member1")
        self.client.login(username="member1", email="member1@example.com", password="testpass")
        response = self._get_landing()
        self.assertNotContains(response, self.LINK_HREF_FRAGMENT)

    def test_link_hidden_for_guest(self):
        self._create("guest1", is_guest=True)
        self.client.login(username="guest1", email="guest1@example.com", password="testpass")
        response = self._get_landing()
        self.assertNotContains(response, self.LINK_HREF_FRAGMENT)

    def test_link_visible_to_officer(self):
        self._create("officer1", is_officer=True)
        self.client.login(username="officer1", email="officer1@example.com", password="testpass")
        response = self._get_landing()
        self.assertContains(response, self.LINK_HREF_FRAGMENT)

    def test_link_visible_to_superuser(self):
        self._create("root", is_superuser=True)
        self.client.login(username="root", email="root@example.com", password="testpass")
        response = self._get_landing()
        self.assertContains(response, self.LINK_HREF_FRAGMENT)
