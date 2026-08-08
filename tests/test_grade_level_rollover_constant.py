"""The academic-year rollover must come from one constant.

The month was hand-written in seven places across the platform and the copies
disagreed — June in package-cis and several tenants, July in csn, May in
form_fields' graduation widget. That is not cosmetic: a widget offering a year
range derived from one rollover, feeding a grade derivation that uses another,
opens a window where every offered year maps to no grade level and
``grade_level`` silently lands blank.

These tests pin the derivation to the constant rather than to a literal, so
changing GRADE_LEVEL_ROLLOVER_MONTH moves the behaviour and nothing else has to
be edited to keep up.
"""
import datetime
from unittest.mock import patch

from django.test import SimpleTestCase

from cis.academic_calendar import (
    GRADE_LEVEL_ROLLOVER_MONTH,
    HIGH_SCHOOL_YEARS,
    graduation_years,
)
from cis.models.student import Student


class _FakeDatetime:
    """Stand-in for the module-level ``datetime`` used by get_grade_level."""

    _today = None

    @classmethod
    def now(cls):
        return datetime.datetime(cls._today.year, cls._today.month, cls._today.day)


def _grade_on(month, graduation_year, year=2026):
    _FakeDatetime._today = datetime.date(year, month, 15)
    with patch('cis.models.student.datetime', _FakeDatetime):
        return Student().get_grade_level(graduation_year=graduation_year)


class RolloverConstantTests(SimpleTestCase):
    def test_constant_is_a_valid_month(self):
        self.assertIn(GRADE_LEVEL_ROLLOVER_MONTH, range(1, 13))

    def test_grade_advances_at_the_constant_not_at_a_literal(self):
        """A 2027 graduate is a junior before the rollover, a senior from it."""
        before = GRADE_LEVEL_ROLLOVER_MONTH - 1
        if before >= 1:
            self.assertEqual(_grade_on(before, 2027), 'JR')
        self.assertEqual(_grade_on(GRADE_LEVEL_ROLLOVER_MONTH, 2027), 'SR')

    def test_every_month_from_the_rollover_reports_the_advanced_grade(self):
        for month in range(GRADE_LEVEL_ROLLOVER_MONTH, 13):
            with self.subTest(month=month):
                self.assertEqual(_grade_on(month, 2027), 'SR')

    def test_every_month_before_the_rollover_reports_the_prior_grade(self):
        for month in range(1, GRADE_LEVEL_ROLLOVER_MONTH):
            with self.subTest(month=month):
                self.assertEqual(_grade_on(month, 2027), 'JR')


class WidgetRangeAgreementTests(SimpleTestCase):
    """The graduation-date widget's year range and the grade derivation must
    turn over in the same month, or the widget offers years that derive to no
    grade at all."""

    def test_tenant_widget_uses_the_shared_constant(self):
        import inspect

        from myce_tenant_configs.services import student_profile_form as mod

        source = inspect.getsource(mod)
        self.assertIn('GRADE_LEVEL_ROLLOVER_MONTH', source)
        # No literal month test may survive alongside the constant.
        self.assertNotIn('month >= 6', source)
        self.assertNotIn('month > 5', source)


class GraduationYearsTests(SimpleTestCase):
    """Every offered graduation year must map to a grade.

    This is the assertion that caught the May drift in sccc: the widget derived
    its year range with one rollover month while get_grade_level used another,
    so for the whole of May the offered years mapped to [JR, SO, FR, None] — a
    blank grade_level, which makes a registration invisible to high school
    admins instead of invalid.
    """

    def test_returns_one_year_per_high_school_grade(self):
        self.assertEqual(len(graduation_years()), HIGH_SCHOOL_YEARS)

    def test_every_offered_year_maps_to_a_grade_in_every_month(self):
        valid = {'FR', 'SO', 'JR', 'SR'}
        for month in range(1, 13):
            as_of = datetime.date(2026, month, 15)
            _FakeDatetime._today = as_of
            with self.subTest(month=month), \
                    patch('cis.models.student.datetime', _FakeDatetime):
                grades = [
                    Student().get_grade_level(graduation_year=y)
                    for y in graduation_years(today=as_of)
                ]
                self.assertEqual(
                    set(grades), valid,
                    f'month {month}: offered years derive to {grades}')

    def test_range_moves_with_the_rollover_constant(self):
        before = datetime.date(2026, max(GRADE_LEVEL_ROLLOVER_MONTH - 1, 1), 15)
        at = datetime.date(2026, GRADE_LEVEL_ROLLOVER_MONTH, 15)
        if GRADE_LEVEL_ROLLOVER_MONTH > 1:
            self.assertEqual(graduation_years(today=before)[0], 2026)
        self.assertEqual(graduation_years(today=at)[0], 2027)

    def test_a_range_derived_from_a_different_rollover_would_break(self):
        """Positive control — proves the invariant above is falsifiable.

        Moving GRADE_LEVEL_ROLLOVER_MONTH cannot break the invariant, because
        the range and the derivation now read the same constant: that is the
        whole point of sharing it. So to show the assertion has teeth, derive a
        range the old way — with May, the value baked into form_fields'
        graduation widget — and confirm it fails while the derivation stays on
        the shared month. This is precisely the sccc regression.
        """
        may_rollover = 5
        self.assertNotEqual(may_rollover, GRADE_LEVEL_ROLLOVER_MONTH,
                            'this control assumes the two months differ')

        as_of = datetime.date(2026, may_rollover, 15)   # inside the bad window
        first = as_of.year + 1 if as_of.month >= may_rollover else as_of.year
        drifted = list(range(first, first + HIGH_SCHOOL_YEARS))

        _FakeDatetime._today = as_of
        with patch('cis.models.student.datetime', _FakeDatetime):
            grades = [Student().get_grade_level(graduation_year=y)
                      for y in drifted]

        self.assertIn(None, grades,
                      'a May-derived range should offer a year with no grade')
        self.assertNotEqual(set(grades), {'FR', 'SO', 'JR', 'SR'})

        # ...while the shared range is clean for that same month.
        with patch('cis.models.student.datetime', _FakeDatetime):
            shared = [Student().get_grade_level(graduation_year=y)
                      for y in graduation_years(today=as_of)]
        self.assertEqual(set(shared), {'FR', 'SO', 'JR', 'SR'})
