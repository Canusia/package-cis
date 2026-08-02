from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser


def _disc():
    r = list(user_logged_in.receivers); user_logged_in.receivers = []; return r


class SettingsOverviewViewTests(TestCase):
    def setUp(self):
        self._s = _disc()
        Group.objects.get_or_create(name='student')
        ce, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            username='sotest', email='sotest@example.com', password='x')
        self.user.groups.add(ce)
        self.client.force_login(self.user)

    def tearDown(self):
        user_logged_in.receivers = self._s

    def test_page_renders_200(self):
        url = reverse('cis:settings_overview', kwargs={'profile': 'student_registration'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Account signup', resp.content)

    def test_page_renders_human_label_not_guid(self):
        from cis.models.term import Term, AcademicYear
        from cis.models.settings import Setting
        from cis.settings.registrations import registrations
        ay = AcademicYear.objects.create(name='2027-2028')
        term = Term.objects.create(label='Spring 2027', code='27SP', academic_year=ay)
        Setting.objects.update_or_create(
            key=registrations.key,
            defaults={'value': {'active_term': str(term.id)}})
        url = reverse('cis:settings_overview', kwargs={'profile': 'student_registration'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Spring 2027', resp.content)          # human label rendered
        self.assertNotIn(str(term.id).encode(), resp.content)  # GUID not shown

    def test_non_admin_rejected(self):
        self.client.logout()
        u = CustomUser.objects.create_user(
            username='plain', email='plain@example.com', password='x')
        self.client.force_login(u)
        url = reverse('cis:settings_overview', kwargs={'profile': 'student_registration'})
        resp = self.client.get(url)
        self.assertIn(resp.status_code, (302, 403))

    def test_unknown_profile_404(self):
        url = reverse('cis:settings_overview', kwargs={'profile': 'bogus'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_superuser_without_ce_role_allowed(self):
        self.client.logout()
        su = CustomUser.objects.create_superuser(
            username='sotest2', email='sotest2@example.com', password='x')
        self.client.force_login(su)
        url = reverse('cis:settings_overview', kwargs={'profile': 'student_registration'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
