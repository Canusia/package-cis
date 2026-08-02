from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSAdministratorAccessRequest


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class AccessRequestTabDispatchTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            username='arqtabtest', email='arqtabtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)

        self.hs = HighSchool.objects.create(
            name='Test High School',
            code='THS',
        )
        self.req = HSAdministratorAccessRequest.objects.create(
            name='Jane Doe',
            email='jane@example.com',
            phone='555-0100',
            highschool=self.hs,
            role='Primary Contact',
        )

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_unknown_tab_returns_404(self):
        resp = self.client.get(reverse('cis:access_request_tab', args=[self.req.id, 'nope']))
        self.assertEqual(resp.status_code, 404)

    def test_additional_info_tab_renders(self):
        resp = self.client.get(reverse('cis:access_request_tab', args=[self.req.id, 'additional_info']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('dataTable', resp.content.decode())

    def test_detail_page_renders_tabs_loop(self):
        resp = self.client.get(reverse('cis:hs_admin_access_request', args=[self.req.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('href="#additional_info"', body)
        self.assertNotIn('href="#notes"', body)          # dropped dead hidden tab
        self.assertIn('id="additional_info"', body)      # eager active pane present
        self.assertIn('tab_loader.js', body)
        self.assertIn('name="status"', body)             # page-shell edit form still rendered
