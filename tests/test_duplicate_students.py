"""Duplicate-student rules: the shared service, the tenant seams, the
CE-configured message, and the Potential Duplicate Students report."""
import datetime
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from cis.models.highschool import HighSchool
from cis.models.settings import Setting
from cis.models.student import Student
from cis.reports.duplicate_students import duplicate_students as DuplicateReport
from cis.services import duplicate_students as dup
from cis.settings.signup import signup

User = get_user_model()
DOB = datetime.date(2008, 12, 10)


def _sfx():
    return uuid.uuid4().hex[:8]


def _student(first='Ada', last='Lovelace', dob=DOB, hs=None, ssn=None, role=True):
    user = User.objects.create_user(
        username=f'u_{_sfx()}', email=f'{_sfx()}@x.com', password='x',
        first_name=first, last_name=last, date_of_birth=dob, ssn=ssn)
    if not role:
        return user
    return Student.objects.create(user=user, highschool=hs)


def _overrides(**attrs):
    """Patch the tenant seam: attrs maps override name -> value."""
    return patch.object(dup, '_override', side_effect=lambda name: attrs.get(name))


class FindDuplicatesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.hs = HighSchool.objects.create(name=f'HS-{_sfx()}')
        cls.other_hs = HighSchool.objects.create(name=f'HS-{_sfx()}')
        cls.existing = _student(hs=cls.hs, ssn='123-45-6789')

    def _values(self, **overrides):
        values = {'first_name': 'Ada', 'last_name': 'Lovelace',
                  'date_of_birth': DOB, 'highschool': self.hs, 'ssn': ''}
        values.update(overrides)
        return values

    def _names(self, matches):
        return [rule['name'] for rule, _students in matches]

    def test_identity_match_ignores_case_and_whitespace(self):
        matches = dup.find_duplicates(
            self._values(first_name='  ada ', last_name='LOVELACE'))
        self.assertEqual(self._names(matches), ['identity'])
        self.assertEqual(matches[0][1], [self.existing])

    def test_twin_with_a_different_first_name_is_not_a_duplicate(self):
        self.assertEqual(dup.find_duplicates(self._values(first_name='Byron')), [])

    def test_different_high_school_is_not_a_duplicate(self):
        self.assertEqual(
            dup.find_duplicates(self._values(highschool=self.other_hs)), [])

    def test_ssn_matches_across_formats(self):
        matches = dup.find_duplicates(
            self._values(first_name='Someone', ssn='123456789'))
        self.assertEqual(self._names(matches), ['ssn'])

    def test_blank_answer_skips_its_rule(self):
        self.assertEqual(
            dup.find_duplicates(self._values(first_name='Someone', ssn='  ')), [])
        self.assertEqual(
            dup.find_duplicates(self._values(date_of_birth=None)), [])

    def test_the_applicants_own_record_is_excluded(self):
        self.assertEqual(
            dup.find_duplicates(self._values(ssn='123456789'),
                                exclude=self.existing), [])

    def test_a_bound_stub_still_matches_someone_else(self):
        """complete_signup binds the stub created at the email step; the stub
        is excluded, the existing student is still found."""
        stub = _student(first='', last='', dob=None)
        matches = dup.find_duplicates(self._values(), exclude=stub)
        self.assertEqual(self._names(matches), ['identity'])

    def test_non_students_are_never_matches(self):
        _student(first='Grace', last='Hopper', ssn='987654321', role=False)
        self.assertEqual(
            dup.find_duplicates(self._values(first_name='Grace',
                                             last_name='Hopper',
                                             ssn='987654321')), [])

    def test_tenant_rules_replace_the_defaults(self):
        with _overrides(RULES=[{'name': 'name_dob',
                                'fields': ['first_name', 'last_name', 'date_of_birth']}]):
            matches = dup.find_duplicates(self._values(highschool=self.other_hs))
        self.assertEqual(self._names(matches), ['name_dob'])

    def test_tenant_field_lookups_extend_the_map(self):
        with _overrides(RULES=[{'name': 'by_email', 'fields': ['email']}],
                        FIELD_LOOKUPS={'email': ('user__email', 'text')}):
            matches = dup.find_duplicates({'email': self.existing.user.email.upper()})
        self.assertEqual(self._names(matches), ['by_email'])

    def test_unknown_field_is_a_configuration_error(self):
        with _overrides(RULES=[{'name': 'typo', 'fields': ['frist_name']}]):
            with self.assertRaises(ImproperlyConfigured):
                dup.get_rules()

    def test_rule_without_a_name_is_a_configuration_error(self):
        with _overrides(RULES=[{'fields': ['first_name']}]):
            with self.assertRaises(ImproperlyConfigured):
                dup.get_rules()


class AddDuplicateErrorsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.hs = HighSchool.objects.create(name=f'HS-{_sfx()}')
        cls.existing = _student(hs=cls.hs)

    def _form(self, readonly=()):
        from django import forms

        class F(forms.Form):
            first_name = forms.CharField()
            last_name = forms.CharField()
            date_of_birth = forms.DateField()
            highschool = forms.ModelChoiceField(queryset=HighSchool.objects.all())

        form = F(data={'first_name': 'Ada', 'last_name': 'Lovelace',
                       'date_of_birth': '2008-12-10', 'highschool': self.hs.pk})
        form.readonly_fields = set(readonly)
        form.is_valid()
        return form

    def test_blocks_with_one_form_error_and_marks_the_fields(self):
        form = self._form()
        self.assertTrue(dup.add_duplicate_errors(form, form.cleaned_data))
        self.assertEqual(form.non_field_errors(), [dup.DEFAULT_MESSAGE])
        for name in ('first_name', 'last_name', 'date_of_birth', 'highschool'):
            self.assertEqual(form.errors[name], [dup.FIELD_MESSAGE])

    def test_rule_with_only_read_only_fields_is_skipped(self):
        form = self._form(readonly=['first_name', 'last_name',
                                    'date_of_birth', 'highschool'])
        self.assertFalse(dup.add_duplicate_errors(form, form.cleaned_data))
        self.assertFalse(form.errors)


class MessageTests(TestCase):
    RULE = {'name': 'identity', 'fields': ['first_name']}

    def _set(self, dup_student):
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'error_messages': json.dumps(
                {'complete_signup': {'dup_student': dup_student}})}})

    def test_falls_back_to_code_wording_when_unset(self):
        self.assertEqual(dup.message_for(self.RULE), dup.DEFAULT_MESSAGE)

    def test_rule_specific_message_wins(self):
        self._set({'default': 'generic', 'identity': 'specific'})
        self.assertEqual(dup.message_for(self.RULE), 'specific')

    def test_default_key_covers_rules_without_their_own(self):
        self._set({'default': 'generic'})
        self.assertEqual(dup.message_for(self.RULE), 'generic')

    def test_malformed_json_falls_back(self):
        Setting.objects.update_or_create(
            key=signup.key, defaults={'value': {'error_messages': '{not json'}})
        self.assertEqual(dup.message_for(self.RULE), dup.DEFAULT_MESSAGE)


class DuplicateReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.hs = HighSchool.objects.create(name=f'HS-{_sfx()}')
        cls.a = _student(hs=cls.hs, ssn='111-22-3333')
        cls.b = _student(first='ADA ', hs=cls.hs)
        cls.c = _student(first='ada', hs=cls.hs)
        cls.twin = _student(first='Byron', hs=cls.hs)
        cls.d = _student(first='Mary', last='Shelley', ssn='111223333')
        _student(first='Ada', last='Lovelace', ssn='111223333', role=False)

    def _rows(self):
        return DuplicateReport().get_rows()

    def test_a_group_of_three_is_one_group_of_three_rows(self):
        identity = [r for r in self._rows() if r[1].startswith('First name')]
        self.assertEqual({r[0] for r in identity}, {identity[0][0]})
        self.assertEqual(sorted(r[2] for r in identity),
                         sorted([self.a.user.id, self.b.user.id, self.c.user.id]))

    def test_ssn_group_matches_across_formats_and_skips_non_students(self):
        ssn = [r for r in self._rows() if r[1] == 'Ssn']
        self.assertEqual(sorted(r[2] for r in ssn),
                         sorted([self.a.user.id, self.d.user.id]))

    def test_twin_is_not_reported(self):
        ids = {r[2] for r in self._rows()}
        self.assertNotIn(self.twin.user.id, ids)

    def test_the_ssn_value_is_never_written(self):
        flat = ' '.join(str(v) for row in self._rows() for v in row)
        self.assertNotIn('111223333', flat)
        self.assertNotIn('111-22-3333', flat)

    def test_rows_line_up_with_the_header(self):
        for row in self._rows():
            self.assertEqual(len(row), len(DuplicateReport.COLUMNS))
