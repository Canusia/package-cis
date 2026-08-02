"""Presentation and per-field validation gaps, per Canusia/ewu#25.

6. a spec entry can describe a field's widget, attrs, bounds and initial
7. a spec entry can attach per-field validators/normalisers

Item 7's shape was decided on the issue: normalisers and validators are ONE
concept — `fn(value, form) -> value`, where raising rejects, returning a value
replaces it, and returning None (what every stock Django validator does) keeps
the original.
"""
import datetime
import uuid

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from cis.forms.application_fields import build_fields
from cis.forms.application_form import SpecDrivenApplicationForm

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def dob_widget():
    """A widget *factory* — the shape a tenant uses to configure something cis
    must not learn about (here, a year range)."""
    return forms.SelectDateWidget(years=range(1990, 2015))


def shout(value, form):
    return value.upper()


def reject_all(value, form):
    raise ValidationError('nope')


def returns_none(value, form):
    """A stock-Django-style validator: checks, returns nothing."""
    return None


class WidgetAndAttrsTests(SimpleTestCase):
    """Item 6."""

    def _one(self, entry):
        built = build_fields(entry)
        return dict(built)[entry['name']]

    def _text(self, **extra):
        entry = {'name': 'first_name', 'type': 'text', 'label': 'First',
                 'target': 'user'}
        entry.update(extra)
        return self._one(entry)

    def test_attrs_reach_the_widget(self):
        field = self._text(attrs={'class': 'form-control col-md-6',
                                  'placeholder': 'Given name'})
        self.assertEqual(field.widget.attrs['class'], 'form-control col-md-6')
        self.assertEqual(field.widget.attrs['placeholder'], 'Given name')

    def test_max_length_validates_and_renders(self):
        field = self._text(max_length=30)
        self.assertEqual(field.max_length, 30)
        # Django surfaces max_length as the maxlength attr on the rendered input
        self.assertEqual(field.widget.attrs['maxlength'], '30')

    def test_initial_passes_through(self):
        field = self._text(name='permanent_address_country', initial='US')
        self.assertEqual(field.initial, 'US')

    def test_widget_dotted_path_replaces_the_default(self):
        field = self._text(widget='django.forms.HiddenInput')
        self.assertIsInstance(field.widget, forms.HiddenInput)

    def test_widget_factory_is_called_for_its_configured_instance(self):
        """A tenant configures a widget cis knows nothing about by pointing at
        a factory; resolution calls it either way."""
        field = self._text(
            name='date_of_birth', type='date',
            widget='cis.tests.test_application_field_presentation.dob_widget')
        self.assertIsInstance(field.widget, forms.SelectDateWidget)
        self.assertEqual(list(field.widget.years)[0], 1990)

    def test_field_class_dotted_path_is_imported_not_called(self):
        field = self._text(field_class='django.forms.URLField')
        self.assertIsInstance(field, forms.URLField)

    def test_attrs_merge_after_a_widget_swap(self):
        """Overriding the widget must not silently drop the field's CSS."""
        field = self._text(widget='django.forms.Textarea',
                           attrs={'class': 'form-control', 'rows': 8})
        self.assertIsInstance(field.widget, forms.Textarea)
        self.assertEqual(field.widget.attrs['class'], 'form-control')
        self.assertEqual(field.widget.attrs['rows'], 8)

    def test_attrs_coexist_with_the_with_meta_data_attrs(self):
        field = self._text(attrs={'class': 'form-control'},
                           validate={'required': 'true'},
                           depends_on={'field': 'no_ssn', 'value': 'True'})
        self.assertEqual(field.widget.attrs['class'], 'form-control')
        self.assertEqual(field.widget.attrs['data-validate-required'], 'true')
        self.assertEqual(field.widget.attrs['data-depends-on'], 'no_ssn')

    def test_max_length_is_not_forced_onto_field_classes_that_reject_it(self):
        """ChoiceField/DateField/BooleanField raise on max_length, so it may
        only reach the text-backed types."""
        for entry in (
            {'name': 'gender', 'type': 'choice', 'label': 'Gender',
             'target': 'student', 'choices': [('m', 'Male')], 'max_length': 10},
            {'name': 'dob', 'type': 'date', 'label': 'DOB', 'target': 'student',
             'max_length': 10},
            {'name': 'agree', 'type': 'agreement', 'label': 'I agree',
             'target': 'meta', 'max_length': 10},
        ):
            with self.subTest(type=entry['type']):
                field = self._one(entry)  # must not raise
                self.assertIsNotNone(field)

    def test_composite_applies_attrs_to_every_part(self):
        built = dict(build_fields({
            'name': 'ssn', 'type': 'ssn', 'label': 'SSN', 'target': 'student',
            'attrs': {'class': 'form-control'},
        }))
        for name in ('ssn', 'verify_ssn', 'no_ssn'):
            self.assertEqual(built[name].widget.attrs['class'], 'form-control',
                             f'{name} lost its attrs')


class FieldValidatorResolutionTests(SimpleTestCase):
    """Item 7: resolution happens at build time, so a typo fails loudly."""

    def _build(self, validators):
        return dict(build_fields({
            'name': 'first_name', 'type': 'text', 'label': 'First',
            'target': 'user', 'validators': validators,
        }))['first_name']

    def test_registry_name_resolves(self):
        field = self._build(['title_case'])
        self.assertEqual(len(field.value_validators), 1)

    def test_dotted_path_resolves(self):
        field = self._build(
            ['cis.tests.test_application_field_presentation.shout'])
        self.assertEqual(field.value_validators[0]('ab', None), 'AB')

    def test_unknown_name_fails_at_build_time(self):
        with self.assertRaises(ImproperlyConfigured):
            self._build(['no_such_validator'])

    def test_validator_class_is_constructed_with_its_kwargs(self):
        """Stock Django/passwords validators are classes needing arguments."""
        field = self._build([
            {'validator': 'passwords.validators.LengthValidator',
             'kwargs': {'min_length': 8}},
        ])
        self.assertEqual(len(field.value_validators), 1)
        # a stock validator's own signature is (value) — the form adapts the
        # arity, so it drops in unchanged
        with self.assertRaises(ValidationError):
            field.value_validators[0]('short')

    def test_validators_attach_only_to_the_named_field_of_a_composite(self):
        built = dict(build_fields({
            'name': 'ssn', 'type': 'ssn', 'label': 'SSN', 'target': 'student',
            'validators': ['title_case'],
        }))
        self.assertTrue(getattr(built['ssn'], 'value_validators', None))
        self.assertFalse(getattr(built['verify_ssn'], 'value_validators', None))
        self.assertFalse(getattr(built['no_ssn'], 'value_validators', None))


class FieldValidatorRunTests(TestCase):
    """Item 7: how they behave on submit.

    A DB test rather than a SimpleTestCase: constructing the form reads the
    tenant's field-wording and field-weight settings."""

    SPEC = [
        {'name': 'first_name', 'type': 'text', 'label': 'First', 'target': 'user',
         'validators': ['title_case']},
    ]

    def _form(self, spec, data, rules=None):
        return SpecDrivenApplicationForm(spec=spec, rules=rules or [], data=data)

    def test_normaliser_rewrites_the_cleaned_value(self):
        form = self._form(self.SPEC, {'first_name': 'jane VAN der berg'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['first_name'], 'Jane Van Der Berg')

    def test_raising_validator_becomes_a_field_error(self):
        spec = [{'name': 'first_name', 'type': 'text', 'label': 'First',
                 'target': 'user',
                 'validators': ['cis.tests.test_application_field_presentation.reject_all']}]
        form = self._form(spec, {'first_name': 'jane'})
        self.assertFalse(form.is_valid())
        self.assertIn('first_name', form.errors)

    def test_validator_returning_none_keeps_the_original_value(self):
        spec = [{'name': 'first_name', 'type': 'text', 'label': 'First',
                 'target': 'user',
                 'validators': ['cis.tests.test_application_field_presentation.returns_none']}]
        form = self._form(spec, {'first_name': 'jane'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['first_name'], 'jane')

    def test_blank_optional_value_skips_the_validators(self):
        spec = [{'name': 'alt_email', 'type': 'text', 'label': 'Alt',
                 'target': 'meta', 'required': False,
                 'validators': ['cis.tests.test_application_field_presentation.reject_all']}]
        form = self._form(spec, {})
        self.assertTrue(form.is_valid(), form.errors)

    def test_validators_run_before_cross_field_rules(self):
        """fields_must_differ must compare normalised values, or two spellings
        of the same phone number slip through."""
        spec = [
            {'name': 'cell_phone', 'type': 'text', 'label': 'Cell',
             'target': 'student', 'validators': ['phone_national']},
            {'name': 'parent_phone', 'type': 'text', 'label': 'Parent',
             'target': 'meta', 'validators': ['phone_national']},
        ]
        rules = [{'rule': 'fields_must_differ',
                  'fields': ['cell_phone', 'parent_phone']}]
        form = self._form(spec, {'cell_phone': '(509) 555-0147',
                                 'parent_phone': '+1 509 555 0147'}, rules)
        self.assertFalse(form.is_valid())
        self.assertIn('parent_phone', form.errors)


class SharedValidatorLibraryTests(SimpleTestCase):
    """The genuinely shared ones cis ships, so no tenant re-implements them."""

    def test_title_case(self):
        from cis.forms.application_validators import title_case
        self.assertEqual(title_case('ada  lovelace', None), 'Ada  Lovelace')

    def test_lower(self):
        from cis.forms.application_validators import lower
        self.assertEqual(lower('Ada@Example.COM', None), 'ada@example.com')

    def test_phone_national_normalises(self):
        from cis.forms.application_validators import phone_national
        self.assertEqual(phone_national('+1 509 555 0147', None),
                         '(509) 555-0147')

    def test_phone_national_rejects_garbage(self):
        from cis.forms.application_validators import phone_national
        with self.assertRaises(ValidationError):
            phone_national('12', None)

    def test_future_date_rejects_today_and_past(self):
        from cis.forms.application_validators import future_date
        with self.assertRaises(ValidationError):
            future_date(timezone.localdate(), None)
        ahead = timezone.localdate() + datetime.timedelta(days=1)
        self.assertEqual(future_date(ahead, None), ahead)


class UniqueUserEmailTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')

    def test_rejects_an_email_already_registered(self):
        from cis.forms.application_validators import unique_user_email

        email = f'taken-{_sfx()}@example.com'
        User.objects.create_user(username=email, email=email, password='x')

        with self.assertRaises(ValidationError):
            unique_user_email(email.upper(), None)

    def test_allows_a_new_email_and_lowercases_it(self):
        from cis.forms.application_validators import unique_user_email

        email = f'Fresh-{_sfx()}@Example.com'
        self.assertEqual(unique_user_email(email, None), email.lower())

    def test_a_student_editing_their_own_record_is_not_a_duplicate(self):
        from cis.forms.application_validators import unique_user_email
        from cis.models.student import Student

        email = f'self-{_sfx()}@example.com'
        user = User.objects.create_user(username=email, email=email, password='x')
        student = Student.objects.create(user=user)

        form = SpecDrivenApplicationForm(spec=[], rules=[], student=student)
        self.assertEqual(unique_user_email(email, form), email)
