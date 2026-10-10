"""School Admins page links to the high school admin portal settings overview."""
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser


class HsAdminSettingsLinkTests(TestCase):
    def setUp(self):
        self._saved, user_logged_in.receivers = list(user_logged_in.receivers), []
        ce, _ = Group.objects.get_or_create(name='ce')
        user = CustomUser.objects.create_superuser(
            username='hslink', email='hslink@example.com', password='x')
        user.groups.add(ce)
        self.client.force_login(user)

    def tearDown(self):
        user_logged_in.receivers = self._saved

    def test_actions_menu_links_to_overview(self):
        resp = self.client.get(reverse('cis:hs_admins'))
        self.assertEqual(resp.status_code, 200)
        href = reverse('cis:settings_overview', kwargs={'profile': 'highschool_admin_portal'})
        self.assertContains(resp, f'href="{href}"')

    def test_access_requests_page_has_no_link(self):
        resp = self.client.get(reverse('cis:hs_admin_access_requests'))
        self.assertNotContains(resp, 'settings-overview/highschool_admin_portal')
