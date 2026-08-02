"""Tests for Student.get_grade_level boundary behavior.

Regression: a student whose graduation_date is a few days in the future
(e.g. graduating mid-June while "today" is early June) was being classified
as 'GRAD' because the helper only looked at the graduation *year* plus a
hardcoded "month >= 6 means already graduated" heuristic. 'GRAD' is 4 chars
and overflowed the varchar(2) grade_level column, raising DataError on save.
"""
import datetime
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.student import Student


def _frozen_now(year=2026, month=6, day=3):
    """Return a patcher that freezes cis.models.student.datetime.now()."""
    fixed = datetime.datetime(year, month, day, 12, 0, 0)

    class _DT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    return patch("cis.models.student.datetime", _DT)


class GetGradeLevelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="student")
        cls.user = CustomUser.objects.create(
            username="grade_user",
            email="grade@example.com",
            first_name="Avi",
            last_name="Kadaji",
        )
        cls.student = Student.objects.create(user=cls.user, gender="m")

    def test_future_graduation_date_in_june_is_senior_not_grad(self):
        # Graduating 2026-06-13, "today" is 2026-06-03 -> still a senior.
        with _frozen_now(2026, 6, 3):
            self.assertEqual(
                self.student.get_grade_level(graduation_date=datetime.date(2026, 6, 13)),
                "SR",
            )

    def test_past_graduation_date_is_grad(self):
        with _frozen_now(2026, 6, 3):
            self.assertEqual(
                self.student.get_grade_level(graduation_date=datetime.date(2026, 6, 1)),
                "GRAD",
            )

    def test_year_only_call_still_advances_after_june(self):
        # No explicit date: the year-only academic-rollover heuristic is preserved.
        with _frozen_now(2026, 6, 3):
            # grad year 2027 -> 1 year out, post-June rollover -> senior.
            self.assertEqual(self.student.get_grade_level(2027), "SR")
