"""Gaps in the spec-driven application engine, per Canusia/ewu#24.

0. PT-20 sanitization must run on the spec path too, not only StudentProfileForm
1. the spec must be able to use the whole with_meta contract
2. choices carry labels; `required` defaults consistently
3. builders receive a ctx, and the runtime-data field types exist
5. student_profile.field_messages() drives wording on both form paths
"""
import datetime
import uuid

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase

from cis.forms.application_fields import build_fields
from cis.forms.application_form import SpecDrivenApplicationForm
from cis.models.student import Student

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class WithMetaPassThroughTests(SimpleTestCase):
    """Item 1: validate / depends_on / copy_when reach the built field."""

    def _one(self, entry):
        built = build_fields(entry)
        self.assertEqual(len(built), 1)
        return built[0][1]

    def test_validate_rules_become_data_attrs(self):
        field = self._one({
            'name': 'first_name', 'type': 'text', 'label': 'First', 'target': 'user',
            'validate': {'required': 'true', 'min-length': '2'},
        })
        self.assertEqual(field.widget.attrs['data-validate-required'], 'true')
        self.assertEqual(field.widget.attrs['data-validate-min-length'], '2')

    def test_depends_on_becomes_data_attrs(self):
        field = self._one({
            'name': 'ssn', 'type': 'text', 'label': 'SSN', 'target': 'meta',
            'depends_on': {'field': 'no_ssn', 'value': 'True', 'negate': True},
        })
        self.assertEqual(field.widget.attrs['data-depends-on'], 'no_ssn')
        self.assertEqual(field.widget.attrs['data-depends-value'], 'True')
        self.assertEqual(field.widget.attrs['data-depends-negate'], 'true')

    def test_copy_when_becomes_copy_metadata(self):
        field = self._one({
            'name': 'mailing_address', 'type': 'text', 'label': 'Mailing',
            'target': 'meta',
            'copy_when': {'trigger': 'same_as_permanent', 'source': 'permanent_address'},
        })
        self.assertEqual(field.copy_trigger, 'same_as_permanent')
        self.assertEqual(field.copy_source, 'permanent_address')


class ChoiceAndRequiredTests(SimpleTestCase):
    """Item 2: labelled choices, and one documented `required` default."""

    def _one(self, entry):
        return build_fields(entry)[0][1]

    def test_choices_accept_value_label_pairs(self):
        field = self._one({'name': 'gender', 'type': 'choice', 'label': 'Gender',
                           'target': 'meta', 'choices': [('m', 'Male'), ('f', 'Female')]})
        self.assertEqual(list(field.choices), [('m', 'Male'), ('f', 'Female')])

    def test_bare_strings_still_become_value_label_pairs(self):
        field = self._one({'name': 'c', 'type': 'choice', 'label': 'C',
                           'target': 'meta', 'choices': ['A', 'B']})
        self.assertEqual(list(field.choices), [('A', 'A'), ('B', 'B')])

    def test_choices_from_resolves_a_dotted_path(self):
        field = self._one({'name': 'ethnicity', 'type': 'choice', 'label': 'Ethnicity',
                           'target': 'student',
                           'choices_from': 'cis.utils.STUDENT_GRADE_OPTIONS'})
        from cis.utils import STUDENT_GRADE_OPTIONS
        self.assertEqual(list(field.choices), list(STUDENT_GRADE_OPTIONS))

    def test_required_defaults_to_true_for_every_type(self):
        for ftype in ('text', 'email', 'choice', 'multichoice', 'agreement'):
            with self.subTest(type=ftype):
                field = self._one({'name': 'f', 'type': ftype, 'label': 'F',
                                   'target': 'meta', 'choices': ['A']})
                self.assertTrue(field.required)

    def test_required_false_is_honoured(self):
        field = self._one({'name': 'f', 'type': 'text', 'label': 'F',
                           'target': 'meta', 'required': False})
        self.assertFalse(field.required)


class RuntimeFieldTypeTests(TestCase):
    """Item 3: builders take a ctx; the runtime-data types exist."""

    def test_builders_receive_ctx_and_date_uses_it(self):
        seen = {}

        from cis.forms import application_fields as af

        def _probe(entry, ctx):
            seen.update(ctx)
            return [(entry['name'], forms.CharField())]

        af.FIELD_TYPES['_probe'] = _probe
        try:
            build_fields({'name': 'x', 'type': '_probe', 'label': 'X', 'target': 'meta'},
                         ctx={'student': 'S', 'request': 'R'})
        finally:
            del af.FIELD_TYPES['_probe']

        self.assertEqual(seen, {'student': 'S', 'request': 'R'})

    def test_date_field(self):
        _, field = build_fields({'name': 'date_of_birth', 'type': 'date',
                                 'label': 'DOB', 'target': 'user'})[0]
        self.assertIsInstance(field, forms.DateField)
        self.assertEqual(field.storage_target, 'user')

    def test_model_choice_queryset_comes_from_the_spec(self):
        from cis.models.highschool import HighSchool

        hs = HighSchool.objects.create(name=f'HS-{_sfx()}')
        _, field = build_fields({
            'name': 'highschool', 'type': 'model_choice', 'label': 'High School',
            'target': 'student', 'queryset': 'cis.models.highschool.HighSchool.objects.all',
        })[0]
        self.assertIsInstance(field, forms.ModelChoiceField)
        self.assertIn(hs, field.queryset)

    def test_password_pair_builds_two_fields(self):
        built = build_fields({'name': 'password', 'type': 'password_pair',
                              'label': 'Password', 'target': 'skip'})
        self.assertEqual([n for n, _ in built], ['password', 'confirm_password'])
        for _, field in built:
            self.assertIsInstance(field.widget, forms.PasswordInput)
            self.assertEqual(field.storage_target, 'skip')

    def test_signature_field(self):
        _, field = build_fields({'name': 'signature', 'type': 'signature',
                                 'label': 'Sign here', 'target': 'meta'})[0]
        self.assertIsInstance(field, forms.CharField)
        self.assertEqual(field.storage_target, 'meta')

    def test_ssn_composite_builds_number_confirm_and_optout(self):
        built = build_fields({'name': 'ssn', 'type': 'ssn', 'label': 'SSN',
                              'target': 'student', 'optout_label': 'I have no SSN'})
        self.assertEqual([n for n, _ in built], ['ssn', 'verify_ssn', 'no_ssn'])
        by_name = dict(built)
        self.assertIsInstance(by_name['no_ssn'], forms.BooleanField)
        self.assertFalse(by_name['no_ssn'].required)
        # the opt-out itself is never persisted to a model column
        self.assertEqual(by_name['no_ssn'].storage_target, 'meta')
        # confirmation is validation-only
        self.assertEqual(by_name['verify_ssn'].storage_target, 'skip')

    def test_ssn_composite_names_are_overridable(self):
        built = build_fields({'name': 'ssn', 'type': 'ssn', 'label': 'SSN',
                              'target': 'student',
                              'verify_name': 'verify_student_ssn',
                              'optout_name': 'student_has_no_ssn'})
        self.assertEqual([n for n, _ in built],
                         ['ssn', 'verify_student_ssn', 'student_has_no_ssn'])


class SpecFormSanitizationTests(TestCase):
    """Item 0: PT-20 sanitization is not bypassed by the spec path."""

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        u = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        cls.student = Student.objects.create(user=u, account_verified=True)

    SPEC = [
        {'name': 'nickname', 'type': 'text', 'label': 'Nickname',
         'required': False, 'target': 'meta'},
    ]

    def test_markup_is_stripped_before_it_reaches_the_student(self):
        form = SpecDrivenApplicationForm(
            spec=self.SPEC, student=self.student,
            data={'nickname': '<script>alert(1)</script>Robbie'})
        self.assertTrue(form.is_valid(), form.errors.as_json())
        form.save()

        self.student.refresh_from_db()
        stored = self.student.meta['nickname']
        self.assertNotIn('<script>', stored)
        self.assertIn('Robbie', stored)

    def test_sanitization_lives_on_the_shared_mixin(self):
        from cis.forms.utils import MetaFormMixin
        self.assertTrue(hasattr(MetaFormMixin, '_sanitize_text_fields'))


class SpecFormFieldMessagesTests(TestCase):
    """Item 5: per-field label/help-text config applies on both form paths."""

    SPEC = [
        {'name': 'nickname', 'type': 'text', 'label': 'Spec label',
         'required': False, 'target': 'meta', 'help_text': 'Spec help'},
    ]

    def test_configured_label_and_help_text_win_over_the_spec(self):
        from unittest.mock import patch

        messages = {'nickname': {'label': 'Preferred name',
                                 'help_text': 'What should we call you?'}}
        with patch('cis.settings.student_profile.student_profile.field_messages',
                   return_value=messages):
            form = SpecDrivenApplicationForm(spec=self.SPEC)

        self.assertEqual(form.fields['nickname'].label, 'Preferred name')
        self.assertEqual(form.fields['nickname'].help_text,
                         'What should we call you?')

    def test_spec_wording_stands_when_nothing_is_configured(self):
        from unittest.mock import patch

        with patch('cis.settings.student_profile.student_profile.field_messages',
                   return_value={}):
            form = SpecDrivenApplicationForm(spec=self.SPEC)

        self.assertEqual(form.fields['nickname'].label, 'Spec label')
        self.assertEqual(form.fields['nickname'].help_text, 'Spec help')
