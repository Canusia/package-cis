"""Roster verification level (package-cis#83).

`verification_level` picks whether the verifier marks the whole class, each
student, or both. A setting saved before it has no key and means 'class', so
reminders and dashboards are unchanged on upgrade. With 'student' a class is
pending while any rostered registration is pending; 'both' takes either rule.
"""
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.customuser import CustomUser
from cis.models.term import AcademicYear, Term
from cis.settings.roster_verification import (
    allows_class_verification, allows_student_verification, verification_level)

ALL_TERMS = {'reminder_terms': 'all'}


class LevelHelperTests(SimpleTestCase):
    def test_missing_key_is_class(self):
        self.assertEqual(verification_level({}), 'class')
        self.assertTrue(allows_class_verification({}))
        self.assertFalse(allows_student_verification({}))

    def test_unknown_value_is_class(self):
        self.assertEqual(verification_level({'verification_level': 'nope'}), 'class')

    def test_student(self):
        values = {'verification_level': 'student'}
        self.assertFalse(allows_class_verification(values))
        self.assertTrue(allows_student_verification(values))

    def test_both(self):
        values = {'verification_level': 'both'}
        self.assertTrue(allows_class_verification(values))
        self.assertTrue(allows_student_verification(values))


class PendingByLevelTests(TestCase):
    def setUp(self):
        # add_note(None, ...) attributes system notes to the 'cron' user.
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        cohort = Cohort.objects.create(name='Eng', designator='ENG')
        course = Course.objects.create(
            catalog_number='101', title='Comp', name='ENG 101', cohort=cohort)
        term = Term.objects.create(
            academic_year=AcademicYear.objects.create(name='2026-2027'),
            code='F26', label='Fall 2026')
        school = HighSchool.objects.create(name='North High', code='NOR')

        def section(number, roster_status):
            return ClassSection.objects.create(
                course=course, term=term, highschool=school,
                class_number=number, section_number='01',
                roster_status=roster_status)

        # Class-level pending, every student already verified.
        self.class_only = section('1', 'Pending Verification')
        # Class verified, one student still pending.
        self.student_only = section('2', 'accurate')
        # Nothing pending.
        self.done = section('3', 'accurate')

        Group.objects.get_or_create(name='student')
        user = CustomUser.objects.create_user(
            username='s1', email='s1@example.com', password='x')
        student = Student.objects.create(user=user)
        StudentRegistration.objects.create(
            student=student, class_section=self.class_only,
            status='registered', status_changed_on={}, verification_status='enrolled')
        StudentRegistration.objects.create(
            student=student, class_section=self.student_only,
            status='registered', status_changed_on={}, verification_status='pending')

    def _pending(self, level, **extra):
        values = dict(ALL_TERMS, **extra)
        if level is not None:
            values['verification_level'] = level
        return set(ClassSection.objects.pending_roster_verification(values))

    def test_default_is_class_level(self):
        self.assertEqual(self._pending(None), {self.class_only})

    def test_class(self):
        self.assertEqual(self._pending('class'), {self.class_only})

    def test_student(self):
        self.assertEqual(self._pending('student'), {self.student_only})

    def test_both(self):
        self.assertEqual(self._pending('both'), {self.class_only, self.student_only})

    def test_student_level_honours_roster_statuses(self):
        self.assertEqual(
            self._pending('student', roster_statuses=['dropped']), set())
