"""Grade-level derivation (ewu#55).

Two defects, one root: the derivation was off by one from the rollover month
through December, and nothing ever recomputed the value afterwards.

The off-by-one came from subtracting calendar years and then patching the
result with a month test. That decrement did two unrelated jobs — roll the
academic year forward (true of everyone) and decide whether this student had
finished (only ever about the graduating class) — and its guard, which existed
for the second, could only act by switching off the first. Since the guard's
condition was merely "is the graduation date in the future", true of every
enrolled student, it suppressed the rollover for the whole student body.

Deriving the senior class year first leaves no decrement to skip.
"""
import datetime
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase

from cis.academic_calendar import (
    GRADUATED,
    UNKNOWN,
    grade_level_from_graduation,
    graduation_years,
    senior_graduation_year,
)
from cis.models.customuser import CustomUser
from cis.models.student import Student

AUG = datetime.date(2026, 8, 7)


class DerivationTests(SimpleTestCase):
    def test_the_four_traces_from_the_issue(self):
        cases = [
            ('year for the graduating class',
             dict(graduation_year=2027, as_of=AUG), 'SR'),
            ('the equivalent date must agree',
             dict(graduation_date=datetime.date(2027, 6, 15), as_of=AUG), 'SR'),
            ('freshman, four years out',
             dict(graduation_date=datetime.date(2030, 6, 15), as_of=AUG), 'FR'),
            ('graduating in ten days is still a senior',
             dict(graduation_date=datetime.date(2027, 6, 15),
                  as_of=datetime.date(2027, 6, 5)), 'SR'),
        ]
        for label, kwargs, expected in cases:
            with self.subTest(label):
                self.assertEqual(grade_level_from_graduation(**kwargs), expected)

    def test_year_and_date_agree_for_every_month_and_class(self):
        """The bug in one assertion: these disagreed for seven months a year."""
        for month in range(1, 13):
            as_of = datetime.date(2026, month, 15)
            for year in range(2025, 2032):
                with self.subTest(month=month, year=year):
                    self.assertEqual(
                        grade_level_from_graduation(
                            graduation_year=year, as_of=as_of),
                        grade_level_from_graduation(
                            graduation_date=datetime.date(year, 6, 1),
                            as_of=as_of))

    def test_every_grade_is_reachable(self):
        grades = [grade_level_from_graduation(graduation_year=y, as_of=AUG)
                  for y in graduation_years(today=AUG)]
        self.assertEqual(grades, ['SR', 'JR', 'SO', 'FR'])

    def test_past_graduation_reports_graduated(self):
        self.assertEqual(
            grade_level_from_graduation(
                graduation_date=datetime.date(2025, 6, 1), as_of=AUG),
            GRADUATED)

    def test_year_outside_high_school_has_no_grade(self):
        self.assertIsNone(
            grade_level_from_graduation(graduation_year=2040, as_of=AUG))

    def test_senior_year_moves_at_the_rollover(self):
        self.assertEqual(senior_graduation_year(datetime.date(2026, 5, 1)), 2026)
        self.assertEqual(senior_graduation_year(datetime.date(2026, 8, 1)), 2027)


class UnreadableInputTests(SimpleTestCase):
    """Must degrade, not raise: get_grade_level is a thin wrapper over this and
    every existing caller inherits the behaviour."""

    def test_string_year_is_accepted(self):
        self.assertEqual(
            grade_level_from_graduation(graduation_year='2027', as_of=AUG), 'SR')

    def test_junk_year_reports_unknown(self):
        self.assertEqual(
            grade_level_from_graduation(graduation_year='abc', as_of=AUG),
            UNKNOWN)

    def test_no_input_reports_unknown(self):
        self.assertEqual(grade_level_from_graduation(as_of=AUG), UNKNOWN)

    def test_empty_string_reports_unknown(self):
        self.assertEqual(
            grade_level_from_graduation(graduation_year='', as_of=AUG), UNKNOWN)

    def test_datetime_is_accepted_as_well_as_date(self):
        self.assertEqual(
            grade_level_from_graduation(
                graduation_date=datetime.datetime(2027, 6, 15, 9, 30),
                as_of=AUG),
            'SR')


class _FakeDatetime:
    _today = AUG

    @classmethod
    def now(cls):
        return datetime.datetime(cls._today.year, cls._today.month,
                                 cls._today.day)


class GetGradeLevelWrapperTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.user = CustomUser.objects.create(username='s', email='s@x.com')

    def _student(self, **kwargs):
        return Student.objects.create(user=self.user, **kwargs)

    def test_no_argument_call_reads_the_date_when_that_is_all_there_is(self):
        """ewu is date-only: graduation_year is NULL for every student, so the
        no-arg path used to return '--' for the entire tenant."""
        student = self._student(graduation_date=datetime.date(2027, 6, 1))
        with patch('cis.models.student.datetime', _FakeDatetime):
            self.assertEqual(student.get_grade_level(), 'SR')

    def test_no_argument_call_reads_the_year_when_that_is_all_there_is(self):
        student = self._student(graduation_year=2027)
        with patch('cis.models.student.datetime', _FakeDatetime):
            self.assertEqual(student.get_grade_level(), 'SR')

    def test_no_graduation_fact_at_all_degrades(self):
        student = self._student()
        with patch('cis.models.student.datetime', _FakeDatetime):
            self.assertEqual(student.get_grade_level(), UNKNOWN)


class RefreshTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.user = CustomUser.objects.create(username='s', email='s@x.com')

    def _student(self, **kwargs):
        return Student.objects.create(user=self.user, **kwargs)

    def test_corrects_a_stale_value(self):
        student = self._student(graduation_date=datetime.date(2027, 6, 1),
                                grade_level='JR')
        self.assertEqual(
            student.refresh_grade_level_from_graduation(save=True, as_of=AUG),
            'SR')
        student.refresh_from_db()
        self.assertEqual(student.grade_level, 'SR')

    def test_is_idempotent(self):
        student = self._student(graduation_date=datetime.date(2027, 6, 1))
        first = student.refresh_grade_level_from_graduation(save=True, as_of=AUG)
        second = student.refresh_grade_level_from_graduation(save=True, as_of=AUG)
        self.assertEqual(first, second)

    def test_does_not_write_without_save(self):
        student = self._student(graduation_date=datetime.date(2027, 6, 1),
                                grade_level='JR')
        student.refresh_grade_level_from_graduation(save=False, as_of=AUG)
        student.refresh_from_db()
        self.assertEqual(student.grade_level, 'JR')

    def test_graduated_student_keeps_their_grade_rather_than_being_blanked(self):
        """A blank grade_level makes a registration invisible to HS admins, so
        an unpersistable sentinel must never overwrite a real value."""
        student = self._student(graduation_date=datetime.date(2020, 6, 1),
                                grade_level='SR')
        self.assertIsNone(
            student.refresh_grade_level_from_graduation(save=True, as_of=AUG))
        student.refresh_from_db()
        self.assertEqual(student.grade_level, 'SR')

    def test_year_outside_high_school_leaves_the_value_alone(self):
        student = self._student(graduation_year=2040, grade_level='FR')
        self.assertIsNone(
            student.refresh_grade_level_from_graduation(save=True, as_of=AUG))
        student.refresh_from_db()
        self.assertEqual(student.grade_level, 'FR')

    def test_no_graduation_fact_leaves_the_value_alone(self):
        student = self._student(grade_level='SO')
        self.assertIsNone(
            student.refresh_grade_level_from_graduation(save=True, as_of=AUG))
        student.refresh_from_db()
        self.assertEqual(student.grade_level, 'SO')

    def test_works_without_account_verified_on(self):
        """csn's version anchors on account_verified_on; deriving straight from
        the graduation fact means a null anchor is not a failure mode."""
        student = self._student(graduation_date=datetime.date(2028, 6, 1),
                                account_verified_on=None)
        self.assertEqual(
            student.refresh_grade_level_from_graduation(save=True, as_of=AUG),
            'JR')
