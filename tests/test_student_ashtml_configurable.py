from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student


class StudentAsHTMLBaselineTests(TestCase):
    """Locks the rendered output of Student.asHTML so the refactor to a
    configurable layout cannot change behaviour when the setting is unset."""

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        cls.user = CustomUser.objects.create(
            username='baseline_student',
            email='baseline@example.com',
            first_name='Jane',
            last_name='Doe',
            psid='-',
        )
        cls.student = Student.objects.create(
            user=cls.user,
            student_id='',
            pidm='',
            parent_first_name='',
            parent_last_name='',
            parent_email='',
            parent1_education_level='',
            parent2_education_level='',
            gender='',
            ethnicity='',
            grade_level='',
            first_gen_student='',
            meta={},
        )

    def _clear_setting(self):
        from cis.settings.student_profile import student_profile
        Setting.objects.filter(key=student_profile.key).delete()

    def test_div_output_contains_expected_labels_and_structure(self):
        self._clear_setting()
        html = self.student.asHTML()
        self.assertIn('<div class="details">', html)
        self.assertIn("<div class='detail_label'>FIRST NAME</div>", html)
        self.assertIn("<div class='detail_label'>EMPLID</div>", html)
        self.assertIn("<div class='detail_label'>MAILING ADDRESS</div>", html)
        self.assertIn("<div class='detail_label'>INTERNAL ID</div>", html)
        self.assertIn('Jane', html)

    def test_div_output_is_stable_across_two_calls(self):
        self._clear_setting()
        self.assertEqual(self.student.asHTML(), self.student.asHTML())

    def test_table_output_uses_table_markup(self):
        self._clear_setting()
        html = self.student.asTable()
        self.assertIn('<table class="table table-striped">', html)
        self.assertIn("<div class='detail_label'>FIRST NAME</div>", html)


class AvailableDisplayFieldsTests(TestCase):
    """The allowed-field list for the profile layout must be driven by
    StudentProfileForm (so it stays in sync) plus an explicit allowlist of
    computed model paths the default layout uses."""

    def test_default_display_is_a_list_of_rows(self):
        from cis.settings.student_profile import DEFAULT_PROFILE_DISPLAY
        self.assertIsInstance(DEFAULT_PROFILE_DISPLAY, list)
        for row in DEFAULT_PROFILE_DISPLAY:
            self.assertIsInstance(row, list)

    def test_available_fields_include_form_fields(self):
        from cis.settings.student_profile import student_profile
        from cis.forms.student_profile import StudentProfileForm
        available = student_profile.available_display_fields()
        for name in StudentProfileForm.base_fields:
            self.assertIn(name, available)

    def test_available_fields_cover_every_key_in_default_display(self):
        from cis.settings.student_profile import (
            student_profile, DEFAULT_PROFILE_DISPLAY,
        )
        available = student_profile.available_display_fields()
        for row in DEFAULT_PROFILE_DISPLAY:
            for column in row:
                key = column['field'] if isinstance(column, dict) else column
                if key == '':
                    continue
                self.assertIn(
                    key, available,
                    f'{key!r} from DEFAULT_PROFILE_DISPLAY is not in the '
                    f'available-fields allow-set',
                )

    def test_available_fields_maps_name_to_human_label(self):
        from cis.settings.student_profile import student_profile
        available = student_profile.available_display_fields()
        self.assertIsInstance(available, dict)
        self.assertEqual(available['user.first_name'], 'First Name')


class ValidateProfileDisplayTests(TestCase):
    def _valid_json(self):
        import json
        from cis.settings.student_profile import DEFAULT_PROFILE_DISPLAY
        return json.dumps(DEFAULT_PROFILE_DISPLAY)

    def test_default_display_serialized_is_valid(self):
        from cis.validators import validate_profile_display
        self.assertEqual(
            validate_profile_display(self._valid_json()), self._valid_json())

    def test_blank_is_allowed(self):
        from cis.validators import validate_profile_display
        self.assertEqual(validate_profile_display(''), '')

    def test_non_json_is_rejected(self):
        from django.core.exceptions import ValidationError
        from cis.validators import validate_profile_display
        with self.assertRaises(ValidationError):
            validate_profile_display('{not json')

    def test_top_level_must_be_a_list(self):
        from django.core.exceptions import ValidationError
        from cis.validators import validate_profile_display
        with self.assertRaises(ValidationError):
            validate_profile_display('{"first_name": "First Name"}')

    def test_row_must_be_a_list(self):
        from django.core.exceptions import ValidationError
        from cis.validators import validate_profile_display
        with self.assertRaises(ValidationError):
            validate_profile_display('["first_name"]')

    def test_dict_column_requires_field_and_label(self):
        from django.core.exceptions import ValidationError
        from cis.validators import validate_profile_display
        with self.assertRaises(ValidationError):
            validate_profile_display('[[{"field": "first_name"}]]')

    def test_unknown_field_key_is_rejected(self):
        from django.core.exceptions import ValidationError
        from cis.validators import validate_profile_display
        with self.assertRaises(ValidationError):
            validate_profile_display('[["not_a_real_field"]]')

    def test_unknown_dict_field_key_is_rejected(self):
        from django.core.exceptions import ValidationError
        from cis.validators import validate_profile_display
        with self.assertRaises(ValidationError):
            validate_profile_display('[[{"field": "bogus", "label": "X"}]]')

    def test_form_field_name_is_accepted(self):
        from cis.validators import validate_profile_display
        self.assertEqual(
            validate_profile_display('[["cell_phone"]]'), '[["cell_phone"]]')

    def test_blank_cell_is_accepted(self):
        from cis.validators import validate_profile_display
        self.assertEqual(validate_profile_display('[["", ""]]'), '[["", ""]]')


class StudentProfileDisplayFormTests(TestCase):
    def _base_data(self, **overrides):
        data = {
            'editable_fields': [],
            'locked_message': '',
            'editable_message': '',
            'profile_review_intro': '',
            'profile_review_template': '<div></div>',
            'profile_display': '',
        }
        data.update(overrides)
        return data

    def test_blank_profile_display_is_valid(self):
        from django.http import HttpRequest
        from cis.settings.student_profile import student_profile
        form = student_profile(HttpRequest(), data=self._base_data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._to_python()['profile_display'], '')

    def test_valid_profile_display_round_trips(self):
        import json
        from django.http import HttpRequest
        from cis.settings.student_profile import (
            student_profile, DEFAULT_PROFILE_DISPLAY,
        )
        payload = json.dumps(DEFAULT_PROFILE_DISPLAY)
        form = student_profile(
            HttpRequest(), data=self._base_data(profile_display=payload))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._to_python()['profile_display'], payload)

    def test_invalid_profile_display_is_rejected(self):
        from django.http import HttpRequest
        from cis.settings.student_profile import student_profile
        form = student_profile(
            HttpRequest(),
            data=self._base_data(profile_display='[["not_a_real_field"]]'))
        self.assertFalse(form.is_valid())
        self.assertIn('profile_display', form.errors)

    def test_install_sets_profile_display_default(self):
        import json
        from django.http import HttpRequest
        from cis.models.settings import Setting
        from cis.settings.student_profile import (
            student_profile, DEFAULT_PROFILE_DISPLAY,
        )
        Setting.objects.filter(key=student_profile.key).delete()
        student_profile(HttpRequest()).install()
        value = student_profile.from_db()
        self.assertEqual(
            json.loads(value['profile_display']), DEFAULT_PROFILE_DISPLAY)


class StudentAsHTMLConfigurableTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        cls.user = CustomUser.objects.create(
            username='cfg_student',
            email='cfg@example.com',
            first_name='Jane',
            last_name='Doe',
            psid='-',
        )
        cls.student = Student.objects.create(
            user=cls.user,
            student_id='',
            pidm='',
            parent_first_name='',
            parent_last_name='',
            parent_email='',
            parent1_education_level='',
            parent2_education_level='',
            gender='',
            ethnicity='',
            grade_level='',
            first_gen_student='',
            meta={},
        )

    def _set_display(self, payload):
        import json
        from cis.settings.student_profile import student_profile
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'profile_display': json.dumps(payload)}},
        )

    def _clear(self):
        from cis.settings.student_profile import student_profile
        Setting.objects.filter(key=student_profile.key).delete()

    def test_unset_setting_matches_default_layout_output(self):
        from cis.utils import model_as_HTML
        from cis.settings.student_profile import DEFAULT_PROFILE_DISPLAY
        self._clear()
        expected = model_as_HTML(self.student, DEFAULT_PROFILE_DISPLAY, 'div')
        self.assertEqual(self.student.asHTML(), expected)

    def test_configured_layout_changes_output(self):
        self._set_display([[{'field': 'user.first_name', 'label': 'Given'}]])
        html = self.student.asHTML()
        self.assertIn("<div class='detail_label'>GIVEN</div>", html)
        self.assertIn('Jane', html)
        self.assertNotIn('EMPLID', html)

    def test_blank_profile_display_falls_back_to_default(self):
        from cis.utils import model_as_HTML
        from cis.settings.student_profile import (
            student_profile, DEFAULT_PROFILE_DISPLAY,
        )
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'profile_display': ''}},
        )
        expected = model_as_HTML(self.student, DEFAULT_PROFILE_DISPLAY, 'div')
        self.assertEqual(self.student.asHTML(), expected)

    def test_malformed_profile_display_falls_back_to_default(self):
        from cis.utils import model_as_HTML
        from cis.settings.student_profile import (
            student_profile, DEFAULT_PROFILE_DISPLAY,
        )
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'profile_display': '{not json'}},
        )
        expected = model_as_HTML(self.student, DEFAULT_PROFILE_DISPLAY, 'div')
        self.assertEqual(self.student.asHTML(), expected)

    def test_table_mode_uses_configured_layout(self):
        self._set_display([[{'field': 'user.first_name', 'label': 'Given'}]])
        html = self.student.asTable()
        self.assertIn('<table class="table table-striped">', html)
        self.assertIn("<div class='detail_label'>GIVEN</div>", html)


class ProfileDisplayHelpTextTests(TestCase):
    def test_help_text_lists_available_fields(self):
        from django.http import HttpRequest
        from cis.settings.student_profile import student_profile
        form = student_profile(HttpRequest())
        help_text = str(form.fields['profile_display'].help_text)
        self.assertIn('cell_phone', help_text)
        self.assertIn('user.first_name', help_text)
