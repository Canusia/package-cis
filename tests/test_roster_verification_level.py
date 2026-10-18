"""Roster verification level (package-cis#83).

`verification_level` picks whether the verifier marks the whole class, each
student, or both. A setting saved before it has no key and means 'class', so
reminders and dashboards are unchanged on upgrade. With 'student' a class is
pending while any rostered registration is pending; 'both' takes either rule.
"""
from unittest import mock

from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase, override_settings

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdminPerm, HSAdministrator, HSAdministratorPosition, HSPosition)
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.models.customuser import CustomUser
from cis.models.term import AcademicYear, Term
from cis.settings.roster_verification import (
    allows_class_verification, allows_student_verification, verification_level)

from .test_roster_verifiers import BASE, FROM_DB, SEND

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


@override_settings(DEBUG=False)
class ReminderRecipientsByLevelTests(TestCase):
    """The reminder cron reaches the same verifiers in every level; the level
    only decides which classes are in each digest."""

    def setUp(self):
        Group.objects.get_or_create(name='highschool_admin')
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        cohort = Cohort.objects.create(name='Eng', designator='ENG')
        course = Course.objects.create(
            catalog_number='101', title='Comp', name='ENG 101', cohort=cohort)
        term = Term.objects.create(
            academic_year=AcademicYear.objects.create(name='2026-2027'),
            code='F26', label='Fall 2026')
        school = HighSchool.objects.create(name='Central High', code='CEN')
        teacher = Teacher.objects.create(user=CustomUser.objects.create_user(
            username='teach', email='teach@example.com', password='x',
            first_name='Tess', last_name='Teacher'))

        admin = HSAdministrator.objects.create(user=CustomUser.objects.create_user(
            username='ayes', email='ayes@example.com', password='x',
            first_name='Ayes', last_name='Admin'))
        HSAdministratorPosition.objects.create(
            hsadmin=admin, highschool=school,
            position=HSPosition.objects.create(name='Counselor'),
            status='Active').grant(HSAdminPerm.VERIFY_ROSTER)

        def section(number, roster_status, student_status):
            record = ClassSection.objects.create(
                course=course, term=term, highschool=school, teacher=teacher,
                class_number=number, section_number=number[-2:],
                roster_status=roster_status)
            user = CustomUser.objects.create_user(
                username=f's{number}', email=f's{number}@example.com', password='x')
            StudentRegistration.objects.create(
                student=Student.objects.create(user=user), class_section=record,
                status='registered', status_changed_on={},
                verification_status=student_status)
            return record

        section('90001', 'pending verification', 'enrolled')   # class pending only
        section('90002', 'accurate', 'pending')                # a student pending only
        section('90003', 'accurate', 'enrolled')               # nothing pending

    def _run(self, level):
        values = {**BASE, **ALL_TERMS,
                  'verifiers': ['instructor', 'highschool_admin'],
                  'request_verify_email': '[{{class_number}}] {{section_list}}',
                  'hsadmin_request_verify_email': '[{{class_number}}] {{section_list}}',
                  'verification_level': level}
        with mock.patch(FROM_DB, return_value=values), mock.patch(SEND) as send:
            _summary, log = ClassSection.notify_sections_pending_roster_verification()
        digests = {tuple(c.args[4]): c.args[1] for c in send.call_args_list}
        return sorted(log['notified_crn']), digests

    def _assert(self, level, crns):
        notified, digests = self._run(level)
        self.assertEqual(notified, crns)
        self.assertEqual(sorted(digests), [('ayes@example.com',), ('teach@example.com',)])
        for html in digests.values():
            for crn in ('90001', '90002', '90003'):
                self.assertEqual(crn in html, crn in crns, (level, crn))

    def test_class(self):
        self._assert('class', ['90001'])

    def test_student(self):
        self._assert('student', ['90002'])

    def test_both(self):
        self._assert('both', ['90001', '90002'])

    def test_nothing_pending_sends_nothing(self):
        StudentRegistration.objects.update(verification_status='enrolled')
        ClassSection.objects.update(roster_status='accurate')
        for level in ('class', 'student', 'both'):
            notified, digests = self._run(level)
            self.assertEqual((notified, digests), ([], {}), level)
