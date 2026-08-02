from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.highschool import HighSchool


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class HighSchoolTabDispatchTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            username='hstabtest', email='hstabtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)

        # HighSchool requires only name (+ code which defaults to '-').
        # district, access_approver are nullable. unique_together = ['name', 'code'].
        self.hs = HighSchool.objects.create(
            name='Test High School',
            code='THS',
        )

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_unknown_tab_returns_404(self):
        resp = self.client.get(reverse('cis:highschool_tab', args=[self.hs.id, 'nope']))
        self.assertEqual(resp.status_code, 404)

    def test_lazy_tabs_render(self):
        for slug in ['instructors', 'class_sections', 'registrations_summary',
                     'drop_wd', 'administrators', 'visits', 'applicants',
                     'transcripts', 'notes']:
            resp = self.client.get(reverse('cis:highschool_tab', args=[self.hs.id, slug]))
            self.assertEqual(resp.status_code, 200, slug)

    def test_applicants_filter_url_not_html_escaped(self):
        """Regression: _applicants.html renders teacher_app_api_url in a <script>
        string; the & must stay literal (mark_safe) so the highschool_id filter is
        sent, else the tab shows every high school's applications."""
        body = self.client.get(
            reverse('cis:highschool_tab', args=[self.hs.id, 'applicants'])).content.decode()
        self.assertIn('&highschool_id=%s' % self.hs.id, body)
        self.assertNotIn('&amp;highschool_id', body)

    def test_details_tab_renders_form(self):
        resp = self.client.get(reverse('cis:highschool_tab', args=[self.hs.id, 'details']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('csrfmiddlewaretoken', resp.content.decode())

    def test_migrate_tab_renders(self):
        resp = self.client.get(reverse('cis:highschool_tab', args=[self.hs.id, 'migrate']))
        self.assertEqual(resp.status_code, 200)

    def test_detail_page_renders_tabs_loop(self):
        resp = self.client.get(reverse('cis:hs_detail', args=[self.hs.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for slug in ['details', 'instructors', 'class_sections', 'registrations_summary',
                     'drop_wd', 'administrators', 'visits', 'applicants', 'transcripts',
                     'notes', 'migrate']:
            self.assertIn('href="#%s"' % slug, body)
        self.assertNotIn('href="#future_courses"', body)
        self.assertNotIn('href="#college_advisors"', body)
        self.assertIn('id="instructors" data-tab-url=', body)
        self.assertIn('tab_loader.js', body)
