"""package-highschool_admin#20 — the student CSV importer accepts the values
counselors' own SIS exports produce.

* dates: MM/DD/YYYY, M/D/YYYY, MM-DD-YYYY, M-D-YYYY, YYYY-MM-DD, YYYY/MM/DD;
  two-digit years are rejected with a message that names the accepted formats;
* yes/no choice columns: whitespace and case are ignored, and y/n, true/false,
  1/0 map onto the field's own Yes/No choice values;
* a blank optional yes/no cell is stored as "No" only for the fields a tenant
  opts in (IMPORT_BLANK_AS_NO_FIELDS); everything else keeps its blank.

Asserted on fields declared here rather than on a tenant's field names, so the
suite holds on every tenant: tests subclass the row form and add the fields.
"""
import datetime

from django import forms
from unittest import mock

from django.test import TestCase, override_settings

from cis.forms.student_import import StudentImportRowForm
from cis.services.importers.student_import_schema import StudentImportColumns


YES_NO_STR = [('', 'Select an Option'), ('Yes', 'Yes'), ('No', 'No')]
# cis.utils.YES_NO_OPTIONS shape: integer values, Yes/No labels.
YES_NO_INT = [('', 'Select an Option'), (1, 'Yes'), (2, 'No')]


class _Form(StudentImportRowForm):
    iep = forms.ChoiceField(choices=YES_NO_STR, required=False)
    plan_504 = forms.ChoiceField(choices=YES_NO_STR, required=False)
    coded = forms.ChoiceField(choices=YES_NO_INT, required=False)
    must_answer = forms.ChoiceField(choices=YES_NO_STR, required=True)
    three_way = forms.ChoiceField(
        choices=[('', '-'), ('1', 'Yes'), ('2', 'No'), ('3', 'Prefer Not to Say')],
        required=False)
    phone_kind = forms.ChoiceField(
        choices=[('Mobile', 'Cell'), ('Home', 'Home')], required=False)
    hispanic = forms.ChoiceField(choices=YES_NO_INT, required=False)

    BLANK_AS_NO_FIELDS = ('iep', 'plan_504', 'coded', 'must_answer')


def _clean(form_cls=_Form, **data):
    form = form_cls(data=data)
    form.is_valid()
    return form


class YesNoNormalizationTests(TestCase):

    def test_case_and_whitespace_are_ignored(self):
        for raw in ('yes', 'YES', ' Yes', 'Yes ', 'yEs'):
            form = _clean(iep=raw)
            self.assertNotIn('iep', form.errors, raw)
            self.assertEqual(form.cleaned_data['iep'], 'Yes', raw)

    def test_synonyms_map_onto_the_choice_values(self):
        cases = {'y': 'Yes', 'Y': 'Yes', 'true': 'Yes', 'TRUE': 'Yes',
                 '1': 'Yes', 'n': 'No', 'N': 'No', 'false': 'No',
                 'False': 'No', '0': 'No', 'no': 'No'}
        for raw, expected in cases.items():
            form = _clean(plan_504=raw)
            self.assertNotIn('plan_504', form.errors, raw)
            self.assertEqual(form.cleaned_data['plan_504'], expected, raw)

    def test_integer_valued_yes_no_maps_by_label(self):
        for raw, expected in (('yes', '1'), ('Y', '1'), ('no', '2'),
                              ('false', '2'), ('0', '2'), ('1', '1'),
                              ('2', '2')):
            form = _clean(coded=raw)
            self.assertNotIn('coded', form.errors, raw)
            self.assertEqual(str(form.cleaned_data['coded']), expected, raw)

    def test_unrecognised_value_is_still_an_error(self):
        form = _clean(iep='maybe')
        self.assertIn('iep', form.errors)

    def test_blank_optional_yes_no_is_no(self):
        form = _clean(iep='', coded='   ')
        self.assertEqual(form.cleaned_data['iep'], 'No')
        self.assertEqual(str(form.cleaned_data['coded']), '2')

    def test_missing_optional_yes_no_column_is_no(self):
        form = _clean()
        self.assertEqual(form.cleaned_data['plan_504'], 'No')

    def test_blank_required_yes_no_stays_an_error(self):
        # A required answer (e.g. a citizenship question) must never be
        # silently answered "No" on the counselor's behalf.
        form = _clean(must_answer='')
        self.assertIn('must_answer', form.errors)

    def test_blank_self_identification_is_not_answered(self):
        form = _clean(hispanic='')
        self.assertIn(form.cleaned_data.get('hispanic'), ('', None))

    def test_blank_stays_blank_unless_the_field_is_opted_in(self):
        class _NotListed(_Form):
            BLANK_AS_NO_FIELDS = ()

        form = _clean(_NotListed, iep='')
        self.assertEqual(form.cleaned_data['iep'], '')

    def test_tenant_seam_opts_fields_in(self):
        class _NotListed(_Form):
            BLANK_AS_NO_FIELDS = ()

        with mock.patch('cis.forms.student_profile.tenant_import_blank_as_no_fields',
                        return_value=('iep',)):
            form = _clean(_NotListed, iep='', plan_504='')
        self.assertEqual(form.cleaned_data['iep'], 'No')
        self.assertEqual(form.cleaned_data['plan_504'], '')

    def test_non_binary_choice_fields_get_no_blank_default(self):
        form = _clean(three_way='')
        self.assertEqual(form.cleaned_data['three_way'], '')
        form = _clean(three_way='yes')
        self.assertEqual(form.cleaned_data['three_way'], '1')

    def test_other_choice_fields_match_case_insensitively(self):
        form = _clean(phone_kind='mobile')
        self.assertNotIn('phone_kind', form.errors)
        self.assertEqual(form.cleaned_data['phone_kind'], 'Mobile')

    def test_raw_data_is_not_mutated(self):
        data = {'iep': ' yes '}
        _Form(data=data).is_valid()
        self.assertEqual(data, {'iep': ' yes '})


class BooleanNormalizationTests(TestCase):

    def test_checkbox_no_values_are_false(self):
        class _B(StudentImportRowForm):
            flag = forms.BooleanField(required=False)

        for raw, expected in (('no', False), ('N', False), ('0', False),
                              ('false', False), ('', False), ('yes', True),
                              ('Y', True), ('1', True), ('TRUE', True)):
            form = _clean(_B, flag=raw)
            self.assertEqual(form.cleaned_data['flag'], expected, raw)


class DateFormatTests(TestCase):

    def setUp(self):
        if 'date_of_birth' not in StudentImportRowForm().fields:
            self.skipTest('tenant form has no date_of_birth')

    def _dob(self, raw):
        form = StudentImportRowForm(data={'date_of_birth': raw})
        form.is_valid()
        return form

    def test_common_formats_are_accepted(self):
        for raw in ('05/02/2011', '5/2/2011', '05-02-2011', '5-2-2011',
                    '2011-05-02', '2011/05/02', ' 05/02/2011 '):
            form = self._dob(raw)
            self.assertNotIn('date_of_birth', form.errors, raw)
            self.assertEqual(form.cleaned_data['date_of_birth'],
                             datetime.date(2011, 5, 2), raw)

    def test_two_digit_year_is_rejected_with_the_accepted_formats(self):
        for raw in ('5/2/11', '05-02-11'):
            form = self._dob(raw)
            self.assertIn('date_of_birth', form.errors, raw)
            msg = ' '.join(form.errors['date_of_birth'])
            self.assertIn('four-digit year', msg)
            self.assertIn('MM/DD/YYYY', msg)

    def test_not_a_real_date_is_rejected(self):
        form = self._dob('02/30/2011')
        self.assertIn('date_of_birth', form.errors)
        self.assertIn('MM/DD/YYYY', ' '.join(form.errors['date_of_birth']))

    def test_format_list_is_overridable_by_settings(self):
        with override_settings(STUDENT_IMPORT_DATE_INPUT_FORMATS=['%d.%m.%Y']):
            form = self._dob('02.05.2011')
            self.assertEqual(form.cleaned_data.get('date_of_birth'),
                             datetime.date(2011, 5, 2))
            self.assertIn('date_of_birth', self._dob('05/02/2011').errors)

    def test_untranslated_directive_survives_param_formatting(self):
        # Tenant date fields re-raise 'invalid' with params={'value': ...};
        # Django then applies message % params, which a bare '%b' would break.
        with override_settings(STUDENT_IMPORT_DATE_INPUT_FORMATS=['%b %d, %Y']):
            form = StudentImportRowForm()
            message = form.fields['date_of_birth'].error_messages['invalid']
            rendered = message % {'value': 'x'}
        self.assertIn('%b', rendered)

    def test_display_formats(self):
        self.assertEqual(
            StudentImportRowForm.accepted_date_formats(),
            ['MM/DD/YYYY', 'M/D/YYYY', 'MM-DD-YYYY', 'M-D-YYYY',
             'YYYY-MM-DD', 'YYYY/MM/DD'])


class ColumnNotesTests(TestCase):
    """field_definitions() carries a per-column note generated from the row
    form, so the upload pages need not hardcode format rules."""

    def test_notes_describe_yes_no_and_date_columns(self):
        notes = _Form.column_notes()
        self.assertIn('blank = No', notes['iep'])
        self.assertIn('Yes', notes['iep'])
        self.assertNotIn('blank = No', notes['must_answer'])
        self.assertNotIn('blank = No', notes.get('hispanic', ''))
        if 'date_of_birth' in notes:
            self.assertIn('MM/DD/YYYY', notes['date_of_birth'])

    def test_field_definitions_carry_notes(self):
        defs = StudentImportColumns.field_definitions()
        self.assertTrue(all('note' in d for d in defs))
        by_name = {d['name']: d for d in defs}
        if 'date_of_birth' in by_name:
            self.assertIn('YYYY-MM-DD', by_name['date_of_birth']['note'])
