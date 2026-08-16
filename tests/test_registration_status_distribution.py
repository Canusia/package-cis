"""`ClassSection.registration_status_distribution()` — the roster PDF breakdown.

Ported from FLCC (ewu#59 item 3). The block sits under the section header on
the roster PDF and answers "what is the shape of this section's registrations",
which the table below it cannot: the table lists only `registered` rows.
"""
from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from cis.models.customuser import CustomUser
from cis.models.course import Course, Cohort
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term


class RegistrationStatusDistributionTests(TestCase):
    _seq = 0

    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@localhost'})
        self.ay = AcademicYear.objects.create(name='2025-2026')
        self.term = Term.objects.create(
            label='Fall 2025', code='FA25', academic_year=self.ay)
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        self.cohort = Cohort.objects.create(name='English', designator='ENGL')
        self.course = Course.objects.create(
            name='ENGL& 101', title='Comp I', catalog_number='101',
            cohort=self.cohort, status='Active')
        self.section = ClassSection.objects.create(
            course=self.course, term=self.term, highschool=self.hs,
            registration_term=self.term,
            class_number='C00001', section_number='01')

    def _register(self, status, section=None):
        type(self)._seq += 1
        n = type(self)._seq
        user = CustomUser.objects.create(username=f'd{n}', email=f'd{n}@x.com')
        student = Student.objects.create(
            user=user, highschool=self.hs, grade_level='JR')
        return StudentRegistration.objects.create(
            student=student, class_section=section or self.section,
            highschool=self.hs, status=status, status_changed_on={})

    def test_empty_section_has_no_distribution(self):
        self.assertEqual(self.section.registration_status_distribution(), [])

    def test_counts_by_status_label_not_code(self):
        self._register('registered')
        self._register('registered')
        self._register('applied')

        distribution = dict(self.section.registration_status_distribution())

        self.assertEqual(distribution['Registered'], 2)
        self.assertEqual(distribution['Requested'], 1)
        self.assertNotIn('registered', distribution)

    def test_covers_statuses_the_roster_table_omits(self):
        """The roster lists only 'registered'; the breakdown must be wider."""
        self._register('registered')
        self._register('applied')

        labels = [label for label, _ in
                  self.section.registration_status_distribution()]

        self.assertIn('Requested', labels)

    def test_order_follows_status_options_not_alphabetical(self):
        self._register('registered')
        self._register('applied')

        labels = [label for label, _ in
                  self.section.registration_status_distribution()]
        codes = [code for code, _ in StudentRegistration.STATUS_OPTIONS]

        self.assertLess(codes.index('applied'), codes.index('registered'))
        self.assertEqual(labels, ['Requested', 'Registered'])

    def test_zero_count_statuses_are_omitted(self):
        self._register('registered')

        self.assertEqual(
            self.section.registration_status_distribution(),
            [('Registered', 1)])

    def test_status_outside_status_options_still_appears(self):
        """Drifted data must stay visible rather than vanish from the total."""
        self._register('registered')
        StudentRegistration.objects.filter(
            student__user__username__startswith='d').update(status='mystery')

        distribution = self.section.registration_status_distribution()

        self.assertEqual(distribution, [('mystery', 1)])

    def test_other_sections_are_not_counted(self):
        other = ClassSection.objects.create(
            course=self.course, term=self.term, highschool=self.hs,
            registration_term=self.term,
            class_number='C00002', section_number='02')
        self._register('registered')
        self._register('registered', section=other)

        self.assertEqual(
            self.section.registration_status_distribution(),
            [('Registered', 1)])

    def test_is_a_single_query(self):
        for status in ('registered', 'registered', 'applied', 'withdrawn'):
            self._register(status)

        with CaptureQueriesContext(connection) as ctx:
            self.section.registration_status_distribution()

        self.assertEqual(len(ctx), 1)
