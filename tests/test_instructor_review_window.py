"""is_instructor_review_open honours the registration setting's dates.

It used to return True before reading any date. Now a set date closes its
side of the window, and a missing or empty date leaves that side open, so a
tenant with only `starting_date` (no `instructor_review_ending_date`) keeps
reviewing after registration opens.
"""
from datetime import datetime

from django.test import TestCase, override_settings

from cis.models.settings import Setting
from cis.utils import is_instructor_review_open

KEY = 'T_cis_registrations'
NOW = datetime(2026, 10, 18, 12, 0)


@override_settings(CAMPUS_CODE_PREFIX='T')
class InstructorReviewWindowTests(TestCase):
    def _set(self, **values):
        Setting.objects.update_or_create(key=KEY, defaults={'value': values})

    def test_no_setting_is_open(self):
        self.assertTrue(is_instructor_review_open(NOW))

    def test_no_dates_is_open(self):
        self._set()
        self.assertTrue(is_instructor_review_open(NOW))

    def test_empty_dates_are_open(self):
        self._set(starting_date='', instructor_review_ending_date='')
        self.assertTrue(is_instructor_review_open(NOW))

    def test_before_start_is_closed(self):
        self._set(starting_date='11/01/2026')
        self.assertFalse(is_instructor_review_open(NOW))

    def test_after_start_without_end_is_open(self):
        self._set(starting_date='07/01/2026')
        self.assertTrue(is_instructor_review_open(NOW))

    def test_after_end_is_closed(self):
        self._set(starting_date='07/01/2026', instructor_review_ending_date='10/17/2026')
        self.assertFalse(is_instructor_review_open(NOW))

    def test_end_date_is_inclusive(self):
        self._set(starting_date='07/01/2026', instructor_review_ending_date='10/18/2026')
        self.assertTrue(is_instructor_review_open(NOW))

    def test_unparseable_date_is_ignored(self):
        self._set(starting_date='not a date')
        self.assertTrue(is_instructor_review_open(NOW))


class ReviewEndDateFieldTests(TestCase):
    """The registrations setting form exposes the end date again (optional)."""

    def _form(self, value):
        from cis.settings.registrations import RegistrationForm
        form = RegistrationForm.__new__(RegistrationForm)
        form.cleaned_data = {'instructor_review_ending_date': value}
        return form

    def test_field_is_optional(self):
        from cis.settings.registrations import RegistrationForm
        field = RegistrationForm.base_fields['instructor_review_ending_date']
        self.assertFalse(field.required)

    def test_empty_saves_blank(self):
        self.assertEqual(self._form(None).clean_instructor_review_ending_date(), '')

    def test_date_saves_mdy(self):
        value = datetime(2026, 12, 15).date()
        self.assertEqual(
            self._form(value).clean_instructor_review_ending_date(), '12/15/2026')
