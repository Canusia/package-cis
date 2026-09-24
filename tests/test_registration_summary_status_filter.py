"""Registration-summary tables: filter by registration status, show status labels.

The CE "Registrations By High School" (academic year, term) and
"Registrations Summary" (academic year, course) tabs let the user choose which
registration statuses to count — all by default — and show each status's label
("Requested") instead of its code ("applied").
"""
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.customuser import CustomUser
from cis.models.course import Course, Cohort
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term

API = '/ce/api/registration-summary/'


class RegistrationSummaryStatusFilterTests(TestCase):
    _seq = 0

    def setUp(self):
        self._saved_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        Group.objects.get_or_create(name='student')
        ce_group, _ = Group.objects.get_or_create(name='ce')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@localhost'})
        self.user = CustomUser.objects.create_superuser(
            username='regsumtest', email='regsumtest@example.com', password='x')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)

        self.ay = AcademicYear.objects.create(name='2025-2026')
        self.term = Term.objects.create(
            label='Fall 2025', code='FA25', academic_year=self.ay)
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        cohort = Cohort.objects.create(name='English', designator='ENGL')
        self.course = Course.objects.create(
            name='ENGL& 101', title='Comp I', catalog_number='101',
            cohort=cohort, status='Active')
        self.section = ClassSection.objects.create(
            course=self.course, term=self.term, highschool=self.hs,
            registration_term=self.term,
            class_number='C00001', section_number='01')
        self._register('applied')
        self._register('registered')
        self._register('registered')
        self._register('dropped')

    def tearDown(self):
        user_logged_in.receivers = self._saved_receivers

    def _register(self, status):
        type(self)._seq += 1
        n = type(self)._seq
        user = CustomUser.objects.create(username=f'rs{n}', email=f'rs{n}@x.com')
        student = Student.objects.create(
            user=user, highschool=self.hs, grade_level='JR')
        return StudentRegistration.objects.create(
            student=student, class_section=self.section,
            highschool=self.hs, status=status, status_changed_on={})

    def _rows(self, query):
        resp = self.client.get(f'{API}?academic_year_id={self.ay.id}&format=json&{query}')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        return data['results'] if isinstance(data, dict) else data

    def _counts(self, query):
        return {r['status']: r['count'] for r in
                self._rows('records_type=by_highschool_registration_created&' + query)}

    def test_no_status_param_counts_every_status(self):
        self.assertEqual(self._counts(''),
                         {'applied': 1, 'registered': 2, 'dropped': 1})

    def test_status_param_limits_to_the_chosen_statuses(self):
        self.assertEqual(self._counts('status=registered&status=dropped'),
                         {'registered': 2, 'dropped': 1})

    def test_status_param_applies_to_the_default_summary(self):
        statuses = {r['status'] for r in self._rows('status=applied')}
        self.assertEqual(statuses, {'applied'})

    def test_unknown_status_returns_nothing(self):
        self.assertEqual(self._counts('status=__none__'), {})

    def test_rows_carry_the_status_label(self):
        labels = {r['status']: r['status_label'] for r in
                  self._rows('records_type=by_highschool_registration_created')}
        self.assertEqual(labels, {'applied': 'Requested',
                                  'registered': 'Registered',
                                  'dropped': 'Dropped'})

    def test_server_side_table_still_gets_the_status_label(self):
        """drf-datatables drops fields no column asks for; the label must survive."""
        resp = self.client.get(
            f'{API}?academic_year_id={self.ay.id}&format=datatables'
            '&records_type=by_highschool_registration_created&draw=1&start=0&length=-1'
            '&columns[0][data]=status&columns[0][name]=status'
            '&columns[0][searchable]=true&columns[0][orderable]=true')
        self.assertEqual(resp.status_code, 200)
        labels = {r['status_label'] for r in resp.json()['data']}
        self.assertEqual(labels, {'Requested', 'Registered', 'Dropped'})

    def _assert_filter_rendered(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Registration Status', body)
        for code, label in StudentRegistration.STATUS_OPTIONS:
            self.assertIn(f'value="{code}" checked', body)
            self.assertIn(label, body)

    def test_academic_year_hs_summary_tab_has_status_filter(self):
        self._assert_filter_rendered(reverse(
            'cis:academic_year_tab', args=[self.ay.id, 'registration_hs_summary']))

    def test_academic_year_registrations_summary_tab_has_status_filter(self):
        self._assert_filter_rendered(reverse(
            'cis:academic_year_tab', args=[self.ay.id, 'registrations_summary']))

    def test_term_hs_summary_tab_has_status_filter(self):
        self._assert_filter_rendered(reverse(
            'cis:term_tab', args=[self.term.id, 'registration_hs_summary']))

    def test_term_registrations_summary_tab_has_status_filter(self):
        self._assert_filter_rendered(reverse(
            'cis:term_tab', args=[self.term.id, 'registrations_summary']))

    def test_course_registrations_summary_tab_has_status_filter(self):
        self._assert_filter_rendered(reverse(
            'cis:course_tab', args=[self.course.id, 'registrations_summary']))
