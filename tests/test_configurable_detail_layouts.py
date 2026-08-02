"""Configurable detail layouts for StudentRegistration and ClassSection."""
import json
import uuid

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase


class ValidateDisplayLayoutTests(TestCase):

    def test_blank_is_allowed(self):
        from cis.validators import validate_display_layout
        self.assertEqual(validate_display_layout(''), '')
        self.assertEqual(validate_display_layout(None), None)

    def test_valid_layout_passes_and_returns_value(self):
        from cis.validators import validate_display_layout
        payload = json.dumps([['status', {'field': 'course', 'label': 'Course'}], ['', 'term']])
        self.assertEqual(validate_display_layout(payload), payload)

    def test_any_field_string_is_allowed_no_allowset(self):
        from cis.validators import validate_display_layout
        payload = json.dumps([['class_section.course.title', 'totally.made.up.path']])
        self.assertEqual(validate_display_layout(payload), payload)

    def test_non_json_is_rejected(self):
        from cis.validators import validate_display_layout
        with self.assertRaises(ValidationError):
            validate_display_layout('{not json')

    def test_top_level_must_be_list(self):
        from cis.validators import validate_display_layout
        with self.assertRaises(ValidationError):
            validate_display_layout('{"a": 1}')

    def test_row_must_be_list(self):
        from cis.validators import validate_display_layout
        with self.assertRaises(ValidationError):
            validate_display_layout('["status"]')

    def test_dict_column_requires_field_and_label(self):
        from cis.validators import validate_display_layout
        with self.assertRaises(ValidationError):
            validate_display_layout('[[{"field": "status"}]]')

    def test_dict_field_and_label_must_be_strings(self):
        from cis.validators import validate_display_layout
        with self.assertRaises(ValidationError):
            validate_display_layout('[[{"field": "status", "label": 5}]]')

    def test_column_must_be_string_or_object(self):
        from cis.validators import validate_display_layout
        with self.assertRaises(ValidationError):
            validate_display_layout('[[123]]')

    def test_blank_cell_string_is_allowed(self):
        from cis.validators import validate_display_layout
        self.assertEqual(validate_display_layout('[["", ""]]'), '[["", ""]]')


class ResolveDisplayLayoutTests(TestCase):

    DEFAULT = [['a', 'b'], [{'field': 'c', 'label': 'C'}]]

    def test_blank_returns_default(self):
        from cis.utils import resolve_display_layout
        self.assertEqual(resolve_display_layout('', self.DEFAULT), self.DEFAULT)
        self.assertEqual(resolve_display_layout(None, self.DEFAULT), self.DEFAULT)

    def test_valid_json_list_returns_parsed(self):
        from cis.utils import resolve_display_layout
        raw = json.dumps([['x']])
        self.assertEqual(resolve_display_layout(raw, self.DEFAULT), [['x']])

    def test_malformed_json_returns_default(self):
        from cis.utils import resolve_display_layout
        self.assertEqual(resolve_display_layout('{not json', self.DEFAULT), self.DEFAULT)

    def test_non_list_json_returns_default(self):
        from cis.utils import resolve_display_layout
        self.assertEqual(resolve_display_layout('{"a": 1}', self.DEFAULT), self.DEFAULT)


def _make_section():
    """Build a minimal ClassSection object graph for asHTML rendering."""
    from cis.models.course import Course, Cohort
    from cis.models.term import Term, AcademicYear
    from cis.models.section import ClassSection

    cohort = Cohort.objects.create(name='Astronomy', designator='A')
    course = Course.objects.create(
        catalog_number='001', title='Descriptive Astronomy',
        name='A 001', cohort=cohort, stream='SR')
    ay = AcademicYear.objects.create(name='2026-2027')
    term = Term.objects.create(label='Fall 2026', code='26FA', academic_year=ay)
    return ClassSection.objects.create(
        course=course, term=term,
        class_number='A-001-3428', section_number='3428',
        external_sis_id=uuid.uuid4(), meta={})


def _make_registration():
    """Build a minimal StudentRegistration for asHTML rendering."""
    from cis.models.customuser import CustomUser
    from cis.models.student import Student
    from cis.models.section import StudentRegistration

    Group.objects.get_or_create(name='student')
    CustomUser.objects.get_or_create(
        username='cron', defaults={'email': 'cron@example.com'})
    section = _make_section()
    user = CustomUser.objects.create(
        username='reg_stud', email='reg@example.com',
        first_name='Sam', last_name='Student', psid='-')
    student = Student.objects.create(
        user=user, first_gen_student='', grade_level='')
    return StudentRegistration.objects.create(
        student=student, class_section=section,
        status='applied', status_changed_on={})


class DetailLayoutBaselineTests(TestCase):
    """Pins current asHTML output before the layout becomes configurable."""

    def test_section_ashtml_renders_expected_labels(self):
        section = _make_section()
        html = section.asHTML()
        self.assertIn('<div class="details">', html)
        self.assertIn("<div class='detail_label'>STATUS</div>", html)
        self.assertIn("<div class='detail_label'>CLASS NUMBER</div>", html)
        self.assertIn("<div class='detail_label'>META</div>", html)

    def test_registration_ashtml_renders_expected_labels(self):
        reg = _make_registration()
        html = reg.asHTML()
        self.assertIn("<div class='detail_label'>SIS ID</div>", html)
        self.assertIn("<div class='detail_label'>COURSE TITLE</div>", html)
        self.assertIn("<div class='detail_label'>INSTRUCTOR</div>", html)
        self.assertIn("<div class='detail_label'>REVIEWER</div>", html)


class RegistrationProfileSettingTests(TestCase):

    def test_default_is_a_list_of_rows(self):
        from cis.settings.registration_profile import REGISTRATION_DEFAULT_DISPLAY
        self.assertIsInstance(REGISTRATION_DEFAULT_DISPLAY, list)
        for row in REGISTRATION_DEFAULT_DISPLAY:
            self.assertIsInstance(row, list)

    def test_default_serialized_passes_the_validator(self):
        from cis.validators import validate_display_layout
        from cis.settings.registration_profile import REGISTRATION_DEFAULT_DISPLAY
        payload = json.dumps(REGISTRATION_DEFAULT_DISPLAY)
        self.assertEqual(validate_display_layout(payload), payload)

    def test_from_db_empty_when_unset(self):
        from cis.models.settings import Setting
        from cis.settings.registration_profile import registration_profile
        Setting.objects.filter(key=registration_profile.key).delete()
        self.assertEqual(registration_profile.from_db(), {})

    def test_install_sets_default(self):
        from django.http import HttpRequest
        from cis.models.settings import Setting
        from cis.settings.registration_profile import (
            registration_profile, REGISTRATION_DEFAULT_DISPLAY,
        )
        Setting.objects.filter(key=registration_profile.key).delete()
        registration_profile(HttpRequest()).install()
        value = registration_profile.from_db()
        self.assertEqual(
            json.loads(value['profile_display']), REGISTRATION_DEFAULT_DISPLAY)

    def test_form_rejects_invalid_layout(self):
        from django.http import HttpRequest
        from cis.settings.registration_profile import registration_profile
        form = registration_profile(
            HttpRequest(), data={'profile_display': '["status"]'})
        self.assertFalse(form.is_valid())
        self.assertIn('profile_display', form.errors)

    def test_form_accepts_blank_and_round_trips_to_python(self):
        from django.http import HttpRequest
        from cis.settings.registration_profile import registration_profile
        form = registration_profile(HttpRequest(), data={'profile_display': ''})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._to_python()['profile_display'], '')


class RegistrationAsHTMLConfigurableTests(TestCase):

    def _set(self, payload):
        from cis.models.settings import Setting
        from cis.settings.registration_profile import registration_profile
        Setting.objects.update_or_create(
            key=registration_profile.key,
            defaults={'value': {'profile_display': json.dumps(payload)}})

    def _clear(self):
        from cis.models.settings import Setting
        from cis.settings.registration_profile import registration_profile
        Setting.objects.filter(key=registration_profile.key).delete()

    def test_unset_matches_default_layout(self):
        from cis.utils import model_as_HTML
        from cis.settings.registration_profile import REGISTRATION_DEFAULT_DISPLAY
        reg = _make_registration()
        self._clear()
        expected = model_as_HTML(reg, REGISTRATION_DEFAULT_DISPLAY)
        self.assertEqual(reg.asHTML(), expected)

    def test_configured_layout_changes_output(self):
        reg = _make_registration()
        self._set([[{'field': 'sis_id', 'label': 'Banner Reg'}]])
        html = reg.asHTML()
        self.assertIn("<div class='detail_label'>BANNER REG</div>", html)
        self.assertNotIn("<div class='detail_label'>INSTRUCTOR</div>", html)

    def test_malformed_falls_back_to_default(self):
        from cis.utils import model_as_HTML
        from cis.models.settings import Setting
        from cis.settings.registration_profile import (
            registration_profile, REGISTRATION_DEFAULT_DISPLAY,
        )
        reg = _make_registration()
        Setting.objects.update_or_create(
            key=registration_profile.key,
            defaults={'value': {'profile_display': '{not json'}})
        expected = model_as_HTML(reg, REGISTRATION_DEFAULT_DISPLAY)
        self.assertEqual(reg.asHTML(), expected)


class ClassSectionProfileSettingTests(TestCase):

    def test_default_is_a_list_of_rows(self):
        from cis.settings.class_section_profile import CLASS_SECTION_DEFAULT_DISPLAY
        self.assertIsInstance(CLASS_SECTION_DEFAULT_DISPLAY, list)
        for row in CLASS_SECTION_DEFAULT_DISPLAY:
            self.assertIsInstance(row, list)

    def test_default_serialized_passes_the_validator(self):
        from cis.validators import validate_display_layout
        from cis.settings.class_section_profile import CLASS_SECTION_DEFAULT_DISPLAY
        payload = json.dumps(CLASS_SECTION_DEFAULT_DISPLAY)
        self.assertEqual(validate_display_layout(payload), payload)

    def test_from_db_empty_when_unset(self):
        from cis.models.settings import Setting
        from cis.settings.class_section_profile import class_section_profile
        Setting.objects.filter(key=class_section_profile.key).delete()
        self.assertEqual(class_section_profile.from_db(), {})

    def test_install_sets_default(self):
        from django.http import HttpRequest
        from cis.settings.class_section_profile import (
            class_section_profile, CLASS_SECTION_DEFAULT_DISPLAY,
        )
        from cis.models.settings import Setting
        Setting.objects.filter(key=class_section_profile.key).delete()
        class_section_profile(HttpRequest()).install()
        value = class_section_profile.from_db()
        self.assertEqual(
            json.loads(value['profile_display']), CLASS_SECTION_DEFAULT_DISPLAY)

    def test_form_rejects_invalid_layout(self):
        from django.http import HttpRequest
        from cis.settings.class_section_profile import class_section_profile
        form = class_section_profile(
            HttpRequest(), data={'profile_display': '{"a": 1}'})
        self.assertFalse(form.is_valid())
        self.assertIn('profile_display', form.errors)


class ClassSectionAsHTMLConfigurableTests(TestCase):

    def _set(self, payload):
        from cis.models.settings import Setting
        from cis.settings.class_section_profile import class_section_profile
        Setting.objects.update_or_create(
            key=class_section_profile.key,
            defaults={'value': {'profile_display': json.dumps(payload)}})

    def _clear(self):
        from cis.models.settings import Setting
        from cis.settings.class_section_profile import class_section_profile
        Setting.objects.filter(key=class_section_profile.key).delete()

    def test_unset_matches_default_layout(self):
        from cis.utils import model_as_HTML
        from cis.settings.class_section_profile import CLASS_SECTION_DEFAULT_DISPLAY
        section = _make_section()
        self._clear()
        expected = model_as_HTML(section, CLASS_SECTION_DEFAULT_DISPLAY)
        self.assertEqual(section.asHTML(), expected)

    def test_configured_layout_changes_output(self):
        section = _make_section()
        self._set([[{'field': 'class_number', 'label': 'CRN'}]])
        html = section.asHTML()
        self.assertIn("<div class='detail_label'>CRN</div>", html)
        self.assertNotIn("<div class='detail_label'>META</div>", html)

    def test_malformed_falls_back_to_default(self):
        from cis.utils import model_as_HTML
        from cis.models.settings import Setting
        from cis.settings.class_section_profile import (
            class_section_profile, CLASS_SECTION_DEFAULT_DISPLAY,
        )
        section = _make_section()
        Setting.objects.update_or_create(
            key=class_section_profile.key,
            defaults={'value': {'profile_display': '{not json'}})
        expected = model_as_HTML(section, CLASS_SECTION_DEFAULT_DISPLAY)
        self.assertEqual(section.asHTML(), expected)
