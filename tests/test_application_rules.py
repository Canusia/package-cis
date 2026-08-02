"""Cross-field rules for the spec-driven application form (item 4 of #24).

cis ships a registry of the genuinely shared rules; a tenant spec module may
export validate() for anything tenant-specific (e.g. Smarty address
verification). Where the tenant declares ownership of a field, its validate()
runs INSTEAD of the registry rule covering that field — not in addition. An
unknown rule name is a hard error at form construction.
"""
import datetime
import uuid

from django.core.exceptions import ImproperlyConfigured
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from unittest.mock import patch

from cis.forms.application_form import SpecDrivenApplicationForm
from cis.models.highschool import HighSchool
from cis.models.student import Student

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


SSN_SPEC = [
    {'name': 'ssn', 'type': 'ssn', 'label': 'SSN', 'target': 'student'},
]
SSN_RULES = [
    {'rule': 'ssn_gate',
     'fields': {'number': 'ssn', 'verify': 'verify_ssn', 'optout': 'no_ssn'}},
]


class UnknownRuleTests(TestCase):
    def test_unknown_rule_raises_at_construction(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            SpecDrivenApplicationForm(
                spec=SSN_SPEC, rules=[{'rule': 'no_such_rule', 'fields': ['ssn']}])
        self.assertIn('no_such_rule', str(ctx.exception))

    def test_known_rule_constructs(self):
        SpecDrivenApplicationForm(spec=SSN_SPEC, rules=SSN_RULES)


class SsnGateTests(TestCase):
    def _form(self, **data):
        return SpecDrivenApplicationForm(spec=SSN_SPEC, rules=SSN_RULES, data=data)

    def test_number_is_required_when_the_optout_is_unchecked(self):
        form = self._form(ssn='', verify_ssn='')
        self.assertFalse(form.is_valid())
        self.assertIn('ssn', form.errors)

    def test_optout_excuses_the_number(self):
        form = self._form(ssn='', verify_ssn='', no_ssn='on')
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_confirmation_must_match(self):
        form = self._form(ssn='123456789', verify_ssn='987654321')
        self.assertFalse(form.is_valid())
        self.assertIn('verify_ssn', form.errors)

    def test_matching_number_and_confirmation_pass(self):
        form = self._form(ssn='123456789', verify_ssn='123456789')
        self.assertTrue(form.is_valid(), form.errors.as_json())


class MatchAndDifferTests(TestCase):
    SPEC = [
        {'name': 'password', 'type': 'password_pair', 'label': 'Password'},
        {'name': 'cell_phone', 'type': 'text', 'label': 'Cell', 'target': 'user'},
        {'name': 'parent_phone', 'type': 'text', 'label': 'Parent', 'target': 'user'},
    ]
    RULES = [
        {'rule': 'match', 'fields': ['password', 'confirm_password']},
        {'rule': 'fields_must_differ', 'fields': ['cell_phone', 'parent_phone']},
    ]

    def _form(self, **data):
        return SpecDrivenApplicationForm(spec=self.SPEC, rules=self.RULES, data=data)

    def test_match_rejects_a_mismatch(self):
        form = self._form(password='hunter2', confirm_password='hunter3',
                          cell_phone='1', parent_phone='2')
        self.assertFalse(form.is_valid())
        self.assertIn('confirm_password', form.errors)

    def test_match_accepts_equal_values(self):
        form = self._form(password='hunter2', confirm_password='hunter2',
                          cell_phone='1', parent_phone='2')
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_fields_must_differ_rejects_equal_values(self):
        form = self._form(password='p', confirm_password='p',
                          cell_phone='5095551234', parent_phone='5095551234')
        self.assertFalse(form.is_valid())
        self.assertIn('parent_phone', form.errors)


class UniqueStudentTests(TestCase):
    SPEC = [
        {'name': 'first_name', 'type': 'text', 'label': 'First', 'target': 'user'},
        {'name': 'last_name', 'type': 'text', 'label': 'Last', 'target': 'user'},
        {'name': 'date_of_birth', 'type': 'date', 'label': 'DOB', 'target': 'user'},
        {'name': 'highschool', 'type': 'model_choice', 'label': 'HS', 'target': 'student',
         'queryset': 'cis.models.highschool.HighSchool.objects.all'},
    ]
    RULES = [{'rule': 'unique_student',
              'fields': ['first_name', 'last_name', 'date_of_birth', 'highschool']}]

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.hs = HighSchool.objects.create(name=f'HS-{_sfx()}')
        user = User.objects.create_user(
            username=f'dup_{_sfx()}', email=f'dup_{_sfx()}@x.com', password='x',
            first_name='Ada', last_name='Lovelace',
            date_of_birth=datetime.date(2008, 12, 10))
        cls.existing = Student.objects.create(user=user, highschool=cls.hs)

    def _data(self, **overrides):
        data = {'first_name': 'Ada', 'last_name': 'Lovelace',
                'date_of_birth': '2008-12-10', 'highschool': str(self.hs.id)}
        data.update(overrides)
        return data

    def test_duplicate_new_applicant_is_rejected(self):
        form = SpecDrivenApplicationForm(spec=self.SPEC, rules=self.RULES,
                                         data=self._data())
        self.assertFalse(form.is_valid())
        for field in ('first_name', 'last_name', 'date_of_birth', 'highschool'):
            self.assertIn(field, form.errors)

    def test_a_different_person_passes(self):
        form = SpecDrivenApplicationForm(spec=self.SPEC, rules=self.RULES,
                                         data=self._data(first_name='Grace'))
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_an_existing_student_editing_their_own_record_passes(self):
        form = SpecDrivenApplicationForm(spec=self.SPEC, rules=self.RULES,
                                         student=self.existing, data=self._data())
        self.assertTrue(form.is_valid(), form.errors.as_json())


class TenantValidatorTests(TestCase):
    """The escape hatch, and the ownership handoff."""

    def _validator(self, calls):
        def validate(form, cleaned_data):
            calls.append(cleaned_data.get('ssn'))
            form.add_error('ssn', 'tenant says no')
        return validate

    def test_tenant_validate_runs_and_its_errors_surface(self):
        calls = []
        # An explicit spec describes the whole form, so the tenant validator
        # is injected rather than resolved from the tenant module.
        form = SpecDrivenApplicationForm(
            spec=SSN_SPEC, rules=[],
            validator=(self._validator(calls), frozenset()),
            data={'ssn': '123456789'})
        self.assertFalse(form.is_valid())

        self.assertEqual(calls, ['123456789'])
        self.assertIn('tenant says no', str(form.errors['ssn']))

    def test_owned_fields_skip_the_registry_rule_entirely(self):
        """The tenant owns `ssn`, so ssn_gate does not also run — its
        "required" error must not appear alongside the tenant's."""
        calls = []
        form = SpecDrivenApplicationForm(
            spec=SSN_SPEC, rules=SSN_RULES,
            validator=(self._validator(calls), frozenset({'ssn'})),
            data={'ssn': '', 'verify_ssn': ''})
        self.assertFalse(form.is_valid())

        errors = str(form.errors['ssn'])
        self.assertIn('tenant says no', errors)
        self.assertNotIn('required', errors.lower())

    def test_unowned_rules_still_run_alongside_the_tenant_validator(self):
        calls = []
        form = SpecDrivenApplicationForm(
            spec=SSN_SPEC, rules=SSN_RULES,
            validator=(self._validator(calls), frozenset({'something_else'})),
            data={'ssn': '', 'verify_ssn': ''})
        self.assertFalse(form.is_valid())

        self.assertIn('required', str(form.errors['ssn']).lower())
