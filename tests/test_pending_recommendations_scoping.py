"""`get_pending_recommendations` must scope correctly and not go N+1.

Regression tests for ewu#64. Three defects, none previously covered:

1. Only the `student_ids` branch filtered `reviewer__isnull=True`. The
   `highschool_ids` branch did not, so a reviewed registration kept counting as
   pending for the HS admin dashboard, tab, and API as long as its status
   stayed `applied` — the two branches answered different questions under one
   name, and the docstring described only the first.
2. The second branch REASSIGNED `records` rather than narrowing it, so passing
   both arguments silently discarded `student_ids` and returned every pending
   registration at those schools, for all students.
3. The eligibility check looped in Python touching `record.student` and
   `record.class_section.course` with no `select_related`, so query count grew
   with row count.
"""
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from cis.models.customuser import CustomUser
from cis.models.course import Course, Cohort
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSAdministrator
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term


class PendingRecommendationScopingTests(TestCase):
    _seq = 0

    def setUp(self):
        # ewu ships a tenant override for this method
        # (myce_tenant_configs/services/registration.py), so on this deployment
        # the cis default never runs. These tests are about the DEFAULT — the
        # body every tenant without an override gets — so force that path.
        override = patch(
            'cis.models.section._tenant_registration_override', return_value=None)
        override.start()
        self.addCleanup(override.stop)

        Group.objects.get_or_create(name='student')
        # The post_save signal on StudentRegistration writes a student note
        # attributed to the 'cron' user; without it every create() blows up.
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@localhost'})
        self.ay = AcademicYear.objects.create(name='2025-2026')
        self.term = Term.objects.create(
            label='Fall 2025', code='FA25', academic_year=self.ay)
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        self.other_hs = HighSchool.objects.create(name='Roosevelt High', status='Active')
        self.cohort = Cohort.objects.create(name='English', designator='ENGL')
        # `reviewer` is an HSAdministrator FK, not a plain user.
        self.reviewer = HSAdministrator.objects.create(
            user=CustomUser.objects.create(
                username='reviewer', email='reviewer@x.com'))

    def _register(self, highschool=None, grade_level='JR',
                  eligibility=None, status='applied', reviewer=None):
        """One applied registration, eligible for recommendation by default."""
        type(self)._seq += 1
        n = type(self)._seq
        if eligibility is None:
            eligibility = [f'{grade_level}*']
        course = Course.objects.create(
            name=f'ENGL& {n}', title='Comp I', catalog_number='101',
            cohort=self.cohort, status='Active',
            registration_eligibility=eligibility)
        section = ClassSection.objects.create(
            course=course, term=self.term, highschool=self.hs,
            registration_term=self.term,
            class_number=f'C{n:05d}', section_number='01')
        user = CustomUser.objects.create(username=f'u{n}', email=f'u{n}@x.com')
        student = Student.objects.create(
            user=user, highschool=highschool or self.hs, grade_level=grade_level)
        return StudentRegistration.objects.create(
            student=student, class_section=section, highschool=self.hs,
            status=status, status_changed_on={}, reviewer=reviewer)

    # --- defect 1: the reviewer check ---------------------------------

    def test_highschool_branch_excludes_reviewed_registrations(self):
        """The defect: reviewed but still 'applied' stayed pending for HS admins."""
        pending = self._register()
        self._register(reviewer=self.reviewer)

        found = StudentRegistration.get_pending_recommendations(
            highschool_ids=[self.hs.id])

        self.assertEqual([r.id for r in found], [pending.id])

    def test_student_branch_excludes_reviewed_registrations(self):
        pending = self._register()
        reviewed = self._register(reviewer=self.reviewer)

        found = StudentRegistration.get_pending_recommendations(
            student_ids=[pending.student.id, reviewed.student.id])

        self.assertEqual([r.id for r in found], [pending.id])

    # --- defect 2: composing both arguments ---------------------------

    def test_passing_both_arguments_intersects(self):
        """Previously student_ids was discarded, returning the whole school."""
        wanted = self._register()
        other_student = self._register()

        found = StudentRegistration.get_pending_recommendations(
            student_ids=[wanted.student.id], highschool_ids=[self.hs.id])

        ids = [r.id for r in found]
        self.assertIn(wanted.id, ids)
        self.assertNotIn(other_student.id, ids,
                         'highschool_ids must narrow student_ids, not replace it')

    def test_both_arguments_can_intersect_to_nothing(self):
        at_this_school = self._register(highschool=self.hs)
        at_other_school = self._register(highschool=self.other_hs)

        found = StudentRegistration.get_pending_recommendations(
            student_ids=[at_other_school.student.id],
            highschool_ids=[self.hs.id])

        self.assertEqual(list(found), [])
        self.assertTrue(at_this_school.id)  # fixture used, silences lint

    # --- scope contract ------------------------------------------------

    def test_no_arguments_returns_nothing(self):
        """Callers pass what they may see; unscoped must not mean unrestricted."""
        self._register()

        self.assertEqual(list(StudentRegistration.get_pending_recommendations()), [])

    def test_ineligible_grade_level_is_excluded(self):
        self._register(grade_level='JR', eligibility=['SR*'])

        found = StudentRegistration.get_pending_recommendations(
            highschool_ids=[self.hs.id])

        self.assertEqual(list(found), [])

    def test_non_applied_status_is_excluded_from_the_highschool_branch(self):
        self._register(status='registered')

        found = StudentRegistration.get_pending_recommendations(
            highschool_ids=[self.hs.id])

        self.assertEqual(list(found), [])

    # --- defect 3: query count ----------------------------------------

    def _query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            list(StudentRegistration.get_pending_recommendations(
                highschool_ids=[self.hs.id]))
        return len(ctx)

    def test_query_count_does_not_grow_with_row_count(self):
        """The eligibility check used to issue one query per row.

        Asserting constancy rather than a fixed number: the count is 1 when
        nothing is skipped and 2 when the exclude() runs, and which of those
        applies is not the point — that it stays flat as rows grow is.
        """
        for _ in range(3):
            self._register()
        small = self._query_count()

        for _ in range(9):
            self._register()
        large = self._query_count()

        self.assertEqual(small, large)
        self.assertLessEqual(large, 2)

    def test_query_count_is_flat_when_rows_are_skipped(self):
        """With ineligible rows the exclude() runs; it must still be constant."""
        for _ in range(2):
            self._register(grade_level='JR', eligibility=['SR*'])
            self._register()
        small = self._query_count()

        for _ in range(6):
            self._register(grade_level='JR', eligibility=['SR*'])
            self._register()
        large = self._query_count()

        self.assertEqual(small, large)
        self.assertLessEqual(large, 2)
