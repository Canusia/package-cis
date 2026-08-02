from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.term import AcademicYear, Term


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class TermTabDispatchTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            username='termtabtest', email='termtabtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        academic_year = AcademicYear.objects.create(name='2025-2026')
        self.term = Term.objects.create(
            academic_year=academic_year,
            code='F25',
            label='Fall 2025',
        )

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_unknown_tab_returns_404(self):
        resp = self.client.get(reverse('cis:term_tab', args=[self.term.id, 'nope']))
        self.assertEqual(resp.status_code, 404)

    def test_lazy_tabs_render(self):
        for slug in ['class_sections', 'class_sections_by_hs', 'registrations_summary',
                     'students_summary', 'registration_hs_summary', 'visits', 'drop_wd']:
            resp = self.client.get(reverse('cis:term_tab', args=[self.term.id, slug]))
            self.assertEqual(resp.status_code, 200, slug)

    def test_details_tab_renders_form(self):
        resp = self.client.get(reverse('cis:term_tab', args=[self.term.id, 'details']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('csrfmiddlewaretoken', resp.content.decode())

    def test_migrate_tab_renders(self):
        resp = self.client.get(reverse('cis:term_tab', args=[self.term.id, 'migrate']))
        self.assertEqual(resp.status_code, 200)

    def test_detail_page_renders_tabs_loop(self):
        resp = self.client.get(reverse('cis:term', args=[self.term.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for slug in ['details', 'class_sections', 'class_sections_by_hs',
                     'registrations_summary', 'students_summary',
                     'registration_hs_summary', 'visits', 'drop_wd', 'migrate']:
            self.assertIn('href="#%s"' % slug, body)
        self.assertIn('id="class_sections" data-tab-url=', body)
        self.assertIn('tab_loader.js', body)
