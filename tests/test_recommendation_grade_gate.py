"""The grade-level gate is a setting, and both implementations must honour it.

``Course.registration_eligibility`` marks a grade as needing a recommendation
with a ``*`` suffix. The historical rule required the student's *own* grade to
carry it. `cis.settings.recommendation_policy` makes that half optional:

    gate ON  (default) -- the student's grade must carry the asterisk
    gate OFF           -- any asterisk on the course is enough, whatever the
                          student's grade; a course with no asterisk at all
                          still requires nothing

The rule has two implementations -- exact list membership in Python, and a ``Q``
builder for the ORM -- behind different surfaces (the high-school Pending
Recommendation tab vs the counselor chase-up email and the CE
``missing_recommendation`` report). They have disagreed before, so the last test
here pins them to the same answers on the same fixtures under both settings.
"""
from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from cis.models.customuser import CustomUser
from cis.models.course import Course, Cohort
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student, recommendation_required_q
from cis.models.term import AcademicYear, Term
from cis.services.recommendation_policy import (
    grade_gate_enabled, registration_requires_recommendation)
from cis.settings.recommendation_policy import recommendation_policy


class RecommendationGradeGateTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@localhost'})
        self.ay = AcademicYear.objects.create(name='2025-2026')
        self.term = Term.objects.create(
            label='Fall 2025', code='FA25', academic_year=self.ay)
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        self.cohort = Cohort.objects.create(name='English', designator='ENGL')

    _seq = 0

    def _set_gate(self, enabled):
        Setting.objects.update_or_create(
            key=recommendation_policy.key,
            defaults={'value': {'require_grade_level_match': enabled}})

    def _register(self, grade_level, eligibility, status='registered'):
        """One student at `grade_level` in a course requiring `eligibility`."""
        type(self)._seq += 1
        n = type(self)._seq
        course = Course.objects.create(
            name=f'ENGL& {n}', title='Comp I', catalog_number='101',
            cohort=self.cohort, status='Active',
            registration_eligibility=eligibility)
        section = ClassSection.objects.create(
            course=course, term=self.term, highschool=self.hs,
            registration_term=self.term,
            class_number=f'C{n:05d}', section_number='01')
        user = CustomUser.objects.create(
            username=f'u{n}', email=f'u{n}@x.com')
        student = Student.objects.create(
            user=user, highschool=self.hs, grade_level=grade_level)
        return StudentRegistration.objects.create(
            student=student, class_section=section, highschool=self.hs,
            status=status, status_changed_on={})

    def _matched(self):
        """Ids the ORM half selects."""
        return set(
            StudentRegistration.objects
            .filter(recommendation_required_q())
            .values_list('id', flat=True)
        )

    # -- the default ------------------------------------------------------

    def test_unset_setting_keeps_the_grade_match(self):
        """No Setting row at all must behave exactly as it did before.

        This is what every already-deployed tenant sees, so it is the one that
        must not move.
        """
        self.assertFalse(Setting.objects.filter(
            key=recommendation_policy.key).exists())
        self.assertTrue(grade_gate_enabled())

        matching = self._register('SR', ['SR*'])
        other_grade = self._register('FR', ['SR*'])

        matched = self._matched()
        self.assertIn(matching.id, matched)
        self.assertNotIn(other_grade.id, matched)
        self.assertTrue(matching.needs_recommendation())
        self.assertFalse(other_grade.needs_recommendation())

    def test_install_defaults_to_on(self):
        recommendation_policy(None).install()
        self.assertTrue(grade_gate_enabled())

    def test_install_does_not_overwrite_a_configured_row(self):
        """register_settings calls install() whenever the registry row is
        missing, which can happen while the value row is already configured."""
        self._set_gate(False)
        recommendation_policy(None).install()
        self.assertFalse(grade_gate_enabled())

    # -- gate off ---------------------------------------------------------

    def test_off_matches_a_grade_the_course_does_not_asterisk(self):
        reg = self._register('FR', ['SR*'])
        self.assertNotIn(reg.id, self._matched())
        self.assertFalse(reg.needs_recommendation())

        self._set_gate(False)
        self.assertIn(reg.id, self._matched())
        self.assertTrue(reg.needs_recommendation())

    def test_off_still_excludes_a_course_with_no_asterisk(self):
        """The per-course flag keeps its meaning; only the grade match goes."""
        self._set_gate(False)
        reg = self._register('SR', ['SR', 'JR'])
        self.assertNotIn(reg.id, self._matched())
        self.assertFalse(reg.needs_recommendation())

    def test_off_matches_a_partially_asterisked_course(self):
        self._set_gate(False)
        reg = self._register('SR', ['SR', 'JR*'])
        self.assertIn(reg.id, self._matched())
        self.assertTrue(reg.needs_recommendation())

    # -- blank grade levels -----------------------------------------------

    def test_blank_grade_level_under_both_settings(self):
        """Blank grades are not hypothetical -- the derivation produces them.

        On, a blank grade matches nothing (the historical guard). Off, it
        matches an asterisked course like any other grade, because the grade is
        no longer consulted.
        """
        blank = self._register('', ['SR*'])
        self.assertNotIn(blank.id, self._matched())
        self.assertFalse(blank.needs_recommendation())

        self._set_gate(False)
        self.assertIn(blank.id, self._matched())
        self.assertTrue(blank.needs_recommendation())

    # -- cost -------------------------------------------------------------

    def test_gate_is_resolved_once_per_call_not_once_per_row(self):
        """Reading the setting per row would be an N+1.

        `get_pending_recommendations` tests the rule inside a comprehension over
        every row; the first cut of this feature read the Setting there and took
        the query count from flat to one-per-row. Covered with the gate OFF,
        which is the configuration the sibling tests in
        test_pending_recommendations_scoping do not exercise.
        """
        self._set_gate(False)

        def count():
            with CaptureQueriesContext(connection) as ctx:
                list(StudentRegistration.get_pending_recommendations(
                    highschool_ids=[self.hs.id]))
            return len(ctx)

        for _ in range(2):
            self._register('JR', ['SR*'], status='applied')
        small = count()

        for _ in range(8):
            self._register('JR', ['SR*'], status='applied')
        large = count()

        self.assertEqual(small, large)

    # -- the drift guard --------------------------------------------------

    def test_both_implementations_agree_under_both_settings(self):
        """The Python half and the ORM half must select the same rows.

        They are behind different surfaces -- the HS Pending Recommendation tab
        vs the counselor email and the CE missing_recommendation report -- so a
        disagreement shows up as the tab listing a student the report does not.
        """
        cases = [
            ('SR', ['SR*']),
            ('FR', ['SR*']),
            ('SR', ['SR', 'JR']),
            ('SR', ['SR', 'JR*']),
            ('', ['SR*']),
            ('JR', []),
        ]
        regs = [self._register(g, e) for g, e in cases]

        for enabled in (True, False):
            self._set_gate(enabled)
            matched = self._matched()
            for reg in regs:
                in_python = registration_requires_recommendation(
                    reg.student.grade_level,
                    reg.class_section.course.registration_eligibility)
                with self.subTest(gate=enabled, reg=str(reg.id)):
                    self.assertEqual(
                        in_python, reg.id in matched,
                        'Python and ORM implementations disagree')
                    self.assertEqual(in_python, reg.needs_recommendation())
