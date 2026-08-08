"""Eligibility matching must honour all four "with recommendation" grades.

``Course.registration_eligibility`` offers FR*/SO*/JR*/SR*, but the CE-side
``missing_recommendation`` query enumerated only SO* and FR*, so a course marked
JR* or SR* could never surface there — a configuration option that silently did
nothing.

The blank-grade case is the subtle one. ``registration_eligibility`` is a
MultiSelectField: a list in Python, a comma-joined string in the column. A
student with no grade level yields the token ``'*'``; matched with SQL
``__contains`` that is ``LIKE '%*%'`` and hits *every* course carrying any
asterisk value, while the in-Python implementations do exact list membership and
correctly match nothing. Blank grade levels are not hypothetical — the grade
derivation produces them — so the filter must never match on grade alone.
"""
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.course import Course, Cohort
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student, recommendation_required_q
from cis.models.term import AcademicYear, Term


class RecommendationEligibilityMatchingTests(TestCase):
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
        return set(
            StudentRegistration.objects
            .filter(recommendation_required_q())
            .values_list('id', flat=True)
        )

    def test_all_four_grades_surface(self):
        regs = {
            grade: self._register(grade, [f'{grade}*'])
            for grade in ('FR', 'SO', 'JR', 'SR')
        }
        matched = self._matched()
        for grade, reg in regs.items():
            with self.subTest(grade=grade):
                self.assertIn(reg.id, matched)

    def test_junior_and_senior_are_not_dropped(self):
        """The reported defect: JR*/SR* were absent from the hardcoded query."""
        jr = self._register('JR', ['JR*'])
        sr = self._register('SR', ['SR*'])
        matched = self._matched()
        self.assertIn(jr.id, matched)
        self.assertIn(sr.id, matched)

    def test_grade_without_asterisk_does_not_match(self):
        reg = self._register('SR', ['SR'])
        self.assertNotIn(reg.id, self._matched())

    def test_mismatched_grade_does_not_match(self):
        # Course wants a recommendation from seniors; student is a freshman.
        reg = self._register('FR', ['SR*'])
        self.assertNotIn(reg.id, self._matched())

    def test_blank_grade_level_never_matches(self):
        """`'*'` as a bare token must not match every asterisk course."""
        reg = self._register('', ['FR*', 'SO*', 'JR*', 'SR*'])
        self.assertNotIn(reg.id, self._matched())

    def test_matches_when_course_lists_several_grades(self):
        reg = self._register('JR', ['FR*', 'JR*', 'SR'])
        self.assertIn(reg.id, self._matched())


class SingleDefinitionTests(TestCase):
    """`needs_recommendation` and GRADE_LEVEL were each defined twice on
    Student; the later definition silently won. Deleting the survivor would
    have restored the hardcoded rule with no test failing."""

    def test_needs_recommendation_source_has_no_hardcoded_grades(self):
        import inspect
        source = inspect.getsource(Student.needs_recommendation)
        self.assertNotIn('SO*', source)
        self.assertNotIn('FR*', source)

    def test_student_class_body_defines_each_name_once(self):
        import inspect
        import re

        source = inspect.getsource(Student)
        for name, pattern in (
            ('needs_recommendation', r'^\s{4}def needs_recommendation\b'),
            ('GRADE_LEVEL', r'^\s{4}GRADE_LEVEL\s*='),
        ):
            with self.subTest(name=name):
                hits = re.findall(pattern, source, flags=re.MULTILINE)
                self.assertEqual(
                    len(hits), 1,
                    f'{name} is defined {len(hits)} times on Student; a '
                    f'shadowed duplicate reads as live logic and would become '
                    f'live if the survivor were removed')
