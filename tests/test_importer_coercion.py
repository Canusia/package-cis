"""Shared importer coercion helpers and the class-section plain fixes
(package-cis#114 item 10)."""
import datetime

from django.test import SimpleTestCase, override_settings

from cis.services.importers.class_section_schema import ClassSectionRow
from cis.services.importers.validation import (
    coerce_date, coerce_yes_no, has_two_digit_year, import_date_input_formats)


class CoerceDateTests(SimpleTestCase):
    def test_blank_is_none(self):
        for value in (None, '', '   '):
            self.assertIsNone(coerce_date(value))

    def test_date_passes_through(self):
        d = datetime.date(2026, 6, 1)
        self.assertEqual(coerce_date(d), d)
        self.assertEqual(coerce_date(datetime.datetime(2026, 6, 1, 9)), d)

    def test_default_layouts(self):
        for text in ('2026-06-01', '06/01/2026', '6/1/2026', '06-01-2026', '2026/06/01'):
            self.assertEqual(coerce_date(text), datetime.date(2026, 6, 1), text)

    def test_two_digit_year_rejected_by_default(self):
        with self.assertRaisesRegex(ValueError, 'four-digit year'):
            coerce_date('6/1/26')

    def test_two_digit_year_when_allowed(self):
        self.assertEqual(coerce_date('6/1/26', allow_2digit_year=True),
                         datetime.date(2026, 6, 1))
        self.assertEqual(coerce_date('6-1-26', allow_2digit_year=True),
                         datetime.date(2026, 6, 1))
        # A four-digit date still parses with the knob on.
        self.assertEqual(coerce_date('6/1/2026', allow_2digit_year=True),
                         datetime.date(2026, 6, 1))

    def test_unparseable_names_the_layouts(self):
        with self.assertRaisesRegex(ValueError, 'MM/DD/YYYY'):
            coerce_date('June 1st')

    def test_explicit_formats(self):
        self.assertEqual(coerce_date('01.06.2026', formats=['%d.%m.%Y']),
                         datetime.date(2026, 6, 1))

    def test_has_two_digit_year(self):
        self.assertTrue(has_two_digit_year('5/2/11'))
        self.assertFalse(has_two_digit_year('5/2/2011'))
        self.assertFalse(has_two_digit_year('2011-05-02'))
        self.assertFalse(has_two_digit_year(None))

    def test_generic_setting(self):
        self.assertEqual(import_date_input_formats(('%Y',)), ('%Y',))
        with override_settings(IMPORT_DATE_INPUT_FORMATS=['%d.%m.%Y']):
            self.assertEqual(import_date_input_formats(('%Y',)), ('%d.%m.%Y',))
            self.assertEqual(coerce_date('01.06.2026'), datetime.date(2026, 6, 1))


class CoerceYesNoTests(SimpleTestCase):
    def test_words(self):
        for value in ('Yes', 'y', 'TRUE', 't', '1', ' yes '):
            self.assertIs(coerce_yes_no(value), True, value)
        for value in ('No', 'N', 'false', 'f', '0'):
            self.assertIs(coerce_yes_no(value), False, value)

    def test_blank_is_none(self):
        for value in (None, '', '  '):
            self.assertIsNone(coerce_yes_no(value))

    def test_bool_passes_through(self):
        self.assertIs(coerce_yes_no(True), True)

    def test_other_raises(self):
        with self.assertRaises(ValueError):
            coerce_yes_no('maybe')


class StudentImportFormatsTests(SimpleTestCase):
    """The student importer reads the shared helpers without changing what it
    accepts: the alias still wins, the generic setting is honoured, two-digit
    years stay rejected."""

    def _formats(self):
        from cis.forms.student_import import StudentImportRowMixin
        return StudentImportRowMixin.date_input_formats()

    def test_default_unchanged(self):
        self.assertEqual(self._formats(),
                         ('%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%Y/%m/%d'))

    def test_student_alias_wins(self):
        with override_settings(STUDENT_IMPORT_DATE_INPUT_FORMATS=['%d.%m.%Y'],
                               IMPORT_DATE_INPUT_FORMATS=['%Y']):
            self.assertEqual(self._formats(), ('%d.%m.%Y',))

    def test_generic_setting_applies(self):
        with override_settings(IMPORT_DATE_INPUT_FORMATS=['%d.%m.%Y']):
            self.assertEqual(self._formats(), ('%d.%m.%Y',))

    def test_yes_no_words_still_importable_from_the_form_module(self):
        from cis.forms import student_import
        self.assertIn('y', student_import.YES_WORDS)
        self.assertIn('n', student_import.NO_WORDS)


def _row(**overrides):
    row = {
        'name': 'Fall 2026', 'term_code': 'FA2026', 'reference_number': '12345',
        'section_number': '01', 'course_name': 'BIO 101', 'course_title': 'Biology',
        'registration_term_code': 'FA2026',
    }
    row.update(overrides)
    return row


class ClassSectionPlainFixTests(SimpleTestCase):
    def test_tuition_strips_currency(self):
        self.assertEqual(ClassSectionRow.model_validate(_row(tuition='$225')).tuition, 225.0)
        self.assertEqual(ClassSectionRow.model_validate(_row(tuition=' $1,200.50 ')).tuition, 1200.5)

    def test_tuition_blank_is_zero(self):
        self.assertEqual(ClassSectionRow.model_validate(_row(tuition='')).tuition, 0.0)
        self.assertEqual(ClassSectionRow.model_validate(_row(tuition='  ')).tuition, 0.0)
        self.assertEqual(ClassSectionRow.model_validate(_row()).tuition, 0.0)

    def test_tuition_text_still_fails(self):
        with self.assertRaises(Exception):
            ClassSectionRow.model_validate(_row(tuition='free'))

    def test_reference_number_is_text(self):
        self.assertEqual(ClassSectionRow.model_validate(_row(reference_number='01234')).reference_number, '01234')
        self.assertEqual(ClassSectionRow.model_validate(_row(reference_number='1030-01')).reference_number, '1030-01')
        # An API payload may send a number.
        self.assertEqual(ClassSectionRow.model_validate(_row(reference_number=12345)).reference_number, '12345')

    def test_reference_number_required(self):
        with self.assertRaises(Exception):
            ClassSectionRow.model_validate(_row(reference_number=''))
