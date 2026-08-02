from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.highschool_administrator import HSAdministrator


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class HSAdministratorTabDispatchTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            username='hsadmtabtest', email='hsadmtabtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)

        # HSAdministrator only requires a user (OneToOneField).
        admin_user = CustomUser.objects.create_user(
            username='hsadmin@example.com',
            email='hsadmin@example.com',
            password='x',
        )
        self.admin = HSAdministrator.objects.create(user=admin_user)

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_unknown_tab_returns_404(self):
        resp = self.client.get(reverse('cis:hs_admin_tab', args=[self.admin.id, 'nope']))
        self.assertEqual(resp.status_code, 404)

    def test_lazy_tabs_render(self):
        for slug in ['passwd_reset', 'notes']:
            resp = self.client.get(reverse('cis:hs_admin_tab', args=[self.admin.id, slug]))
            self.assertEqual(resp.status_code, 200, slug)

    def test_highschools_tab_is_active_and_renders(self):
        resp = self.client.get(reverse('cis:hs_admin_tab', args=[self.admin.id, 'highschools']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('dataTable', resp.content.decode())

    def test_detail_page_renders_tabs_loop(self):
        resp = self.client.get(reverse('cis:hs_admin', args=[self.admin.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for slug in ['highschools', 'passwd_reset', 'notes']:
            self.assertIn('href="#%s"' % slug, body)
        self.assertIn('id="passwd_reset" data-tab-url=', body)   # lazy
        self.assertIn('id="highschools"', body)                  # eager active pane present
        self.assertIn('tab_loader.js', body)
