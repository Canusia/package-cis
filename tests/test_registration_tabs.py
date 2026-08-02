"""Tests for registration tab registry wiring."""
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class RegistrationTabDispatchTest(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        # Student.save() calls Group.objects.get(name='student') unconditionally
        Group.objects.get_or_create(name='student')
        # The onboarding context processor calls active_term() which returns
        # Term.objects.first(). We need a Term to avoid IntegrityError.
        academic_year = AcademicYear.objects.create(name='2025-2026')
        term = Term.objects.create(
            label='Fall 2025', code='F25', academic_year=academic_year)
        cohort = Cohort.objects.create(name='Test Cohort', designator='TST')
        course = Course.objects.create(
            catalog_number='101', title='Tab Test', name='TAB101', cohort=cohort)
        section = ClassSection.objects.create(
            course=course, term=term, class_number=99901, section_number='001')
        self.user = CustomUser.objects.create_superuser(
            username='regtabtest', email='regtabtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        # The post_save signal on StudentRegistration calls add_note() which falls
        # back to CustomUser.objects.get(username='cron') when there's no request user.
        CustomUser.objects.create_user(username='cron', email='cron@example.com', password='x')
        student_user = CustomUser.objects.create_user(
            username='regtabstudent', email='regtabstudent@example.com', password='x')
        student = Student.objects.create(user=student_user)
        self.record = StudentRegistration.objects.create(
            student=student,
            class_section=section,
            status_changed_on={},
        )

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def test_unknown_slug_returns_404(self):
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'nonexistent-tab'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_known_slug_returns_200(self):
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'classes'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_classes_tab_returns_200(self):
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'classes'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_recommendation_tab_returns_200(self):
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'recommendation'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_signatures_tab_returns_200(self):
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'signatures'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_notes_tab_returns_200(self):
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'notes'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_edit_registration_tab_returns_200(self):
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'edit_registration'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_edit_registration_tab_post_no_action_rebinds_form(self):
        """POST without action= triggers the registration-update rebind branch."""
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'edit_registration'})
        resp = self.client.post(url, data={})
        self.assertEqual(resp.status_code, 200)

    def test_student_details_tab_returns_200(self):
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'student_details'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_campus_id_tab_returns_200(self):
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'campus_id'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_campus_id_tab_post_edit_campus_rebinds_form(self):
        """POST with action=edit_campus triggers the campus-id rebind branch."""
        url = reverse('cis:registration_tab',
                      kwargs={'record_id': self.record.id,
                              'tab_slug': 'campus_id'})
        resp = self.client.post(url, data={'action': 'edit_campus'})
        self.assertEqual(resp.status_code, 200)

    def test_detail_page_renders_all_tab_anchors(self):
        url = reverse('cis:registration', kwargs={'record_id': self.record.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        for slug in ['edit_registration', 'student_details', 'classes',
                     'recommendation', 'signatures', 'notes']:
            self.assertIn(f'href="#{slug}"', content,
                          msg=f'Missing tab anchor for #{slug}')
        # Lazy panes have data-tab-url; eager panes do not
        self.assertIn('data-tab-url=', content)
        self.assertIn('tab_loader.js', content)

    def test_campus_id_nav_is_hidden(self):
        url = reverse('cis:registration', kwargs={'record_id': self.record.id})
        resp = self.client.get(url)
        content = resp.content.decode()
        self.assertIn('d-none', content)
        self.assertIn('href="#campus_id"', content)
