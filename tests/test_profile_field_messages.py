"""Per-field label/help-text configuration on the student_profile setting."""
import importlib
import json
import types

from django.apps import apps as global_apps

from django import forms
from django.contrib.auth.models import Group
from django.http import QueryDict
from django.test import TestCase

from cis.forms.student_profile import StudentProfileForm
from cis.models import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student
from cis.settings.signup import signup
from cis.settings.student_profile import (
    SIGNUP_MECHANIC_FIELDS,
    ProfileFieldsField,
    message_fields,
    student_profile,
)


class FieldMessagesReadTests(TestCase):
    def _set_profile(self, value):
        Setting.objects.update_or_create(
            key=student_profile.key, defaults={'value': value})

    def _set_signup(self, value):
        Setting.objects.update_or_create(
            key=signup.key, defaults={'value': value})

    def test_returns_empty_when_nothing_configured(self):
        Setting.objects.filter(
            key__in=[student_profile.key, signup.key]).delete()
        self.assertEqual(student_profile.field_messages(), {})

    def test_returns_the_new_key(self):
        self._set_profile({'field_messages': {
            'start_date': {'label': 'Start', 'help_text': 'MM/DD'}}})
        self.assertEqual(
            student_profile.field_messages(),
            {'start_date': {'label': 'Start', 'help_text': 'MM/DD'}})

    def test_falls_back_to_legacy_signup_json(self):
        Setting.objects.filter(key=student_profile.key).delete()
        self._set_signup({'form_field_messages': json.dumps(
            {'email': {'label': 'Your Email'}})})
        self.assertEqual(student_profile.field_messages(),
                         {'email': {'label': 'Your Email'}})

    def test_new_key_wins_over_legacy(self):
        self._set_profile({'field_messages': {'email': {'label': 'New'}}})
        self._set_signup({'form_field_messages': json.dumps(
            {'email': {'label': 'Old'}})})
        self.assertEqual(student_profile.field_messages(),
                         {'email': {'label': 'New'}})

    def test_malformed_legacy_json_is_empty_not_an_error(self):
        Setting.objects.filter(key=student_profile.key).delete()
        self._set_signup({'form_field_messages': '{not json'})
        self.assertEqual(student_profile.field_messages(), {})

    def test_non_dict_new_key_is_empty(self):
        self._set_profile({'field_messages': ['nope']})
        self.assertEqual(student_profile.field_messages(), {})


class WidgetMessagesTests(TestCase):
    def test_renders_a_detail_row_per_profile_field(self):
        html = ProfileFieldsField().widget.render('profile_fields', {})
        self.assertEqual(html.count('class="fw-detail"'),
                         len(message_fields()))
        self.assertIn('data-detail-for="first_name"', html)
        self.assertIn('name="profile_fields_label_first_name"', html)
        self.assertIn('name="profile_fields_help_first_name"', html)

    def test_detail_row_shows_stored_values(self):
        html = ProfileFieldsField().widget.render('profile_fields', {
            'messages': {'email': {'label': 'Your Email',
                                   'help_text': '<b>required</b>'}}})
        self.assertIn('value="Your Email"', html)
        self.assertIn('&lt;b&gt;required&lt;/b&gt;', html)

    def test_configured_row_is_marked_when_collapsed(self):
        html = ProfileFieldsField().widget.render('profile_fields', {
            'messages': {'email': {'label': 'Your Email'}}})
        self.assertIn('data-field="email"', html)
        self.assertIn('fw-configured', html)

    def test_signup_mechanic_fields_get_label_only_rows(self):
        html = ProfileFieldsField().widget.render('profile_fields', {})
        # No grip/weight/checkbox for the mechanics, but a label input each.
        self.assertIn('name="profile_fields_label_password"', html)
        self.assertNotIn('name="profile_fields_weight_password"', html)
        self.assertNotIn('value="password"', html)

    def test_value_from_datadict_collects_messages(self):
        widget = ProfileFieldsField().widget
        data = QueryDict(mutable=True)
        data.update({
            'profile_fields_label_email': 'Your Email',
            'profile_fields_help_email': 'We never share it.',
            'profile_fields_label_first_name': '',
            'profile_fields_help_first_name': '',
        })
        value = widget.value_from_datadict(data, {}, 'profile_fields')
        self.assertEqual(
            value['messages'],
            {'email': {'label': 'Your Email',
                       'help_text': 'We never share it.'}})

    def test_value_from_datadict_keeps_a_lone_help_text(self):
        widget = ProfileFieldsField().widget
        data = QueryDict(mutable=True)
        data.update({'profile_fields_help_email': 'Only help.'})
        value = widget.value_from_datadict(data, {}, 'profile_fields')
        self.assertEqual(value['messages'],
                         {'email': {'help_text': 'Only help.'}})


class FieldCleaningTests(TestCase):
    def test_cleans_messages_through(self):
        cleaned = ProfileFieldsField().clean(
            {'messages': {'email': {'label': 'E', 'help_text': 'H'}}})
        self.assertEqual(cleaned['messages'],
                         {'email': {'label': 'E', 'help_text': 'H'}})

    def test_accepts_signup_mechanic_fields(self):
        cleaned = ProfileFieldsField().clean(
            {'messages': {'password': {'label': 'Create a password'}}})
        self.assertEqual(cleaned['messages'],
                         {'password': {'label': 'Create a password'}})

    def test_rejects_unknown_message_field(self):
        with self.assertRaises(forms.ValidationError):
            ProfileFieldsField().clean(
                {'messages': {'not_a_field': {'label': 'X'}}})

    def test_signup_mechanics_still_rejected_for_editable(self):
        with self.assertRaises(forms.ValidationError):
            ProfileFieldsField().clean({'editable': ['password']})

    def test_rejects_broken_template_shortcode(self):
        with self.assertRaises(forms.ValidationError):
            ProfileFieldsField().clean(
                {'messages': {'email': {'help_text': '{% if %}'}}})


class SettingRoundTripTests(TestCase):
    def _form(self, **kwargs):
        request = types.SimpleNamespace(GET={'report_id': '1'})
        return student_profile(request, **kwargs)

    def test_initial_folds_field_messages_into_the_control(self):
        form = self._form(initial={
            'field_messages': {'email': {'label': 'Your Email'}}})
        self.assertEqual(form.initial['profile_fields']['messages'],
                         {'email': {'label': 'Your Email'}})

    def test_post_stores_field_messages(self):
        data = QueryDict(mutable=True)
        data.update({
            'profile_fields_weight_email': '1',
            'profile_fields_label_email': 'Your Email',
            'profile_fields_help_email': 'We never share it.',
            'locked_message': 'a', 'editable_message': 'b',
            'profile_review_intro': 'c',
            'profile_review_template': '<p>x</p>', 'profile_display': '',
        })
        form = self._form(data=data)
        self.assertTrue(form.is_valid(), form.errors.as_text())
        stored = form._to_python()
        self.assertEqual(stored['field_messages'],
                         {'email': {'label': 'Your Email',
                                    'help_text': 'We never share it.'}})
        self.assertEqual(stored['field_weights'], {'email': 1})

    def test_install_seeds_field_messages_from_legacy_signup(self):
        Setting.objects.filter(key=student_profile.key).delete()
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'form_field_messages': json.dumps(
                {'start_date': {'label': 'When did you start?'}})}})
        student_profile(types.SimpleNamespace(GET={})).install()
        value = student_profile.from_db()
        self.assertEqual(value['field_messages'],
                         {'start_date': {'label': 'When did you start?'}})


class ProfileFormWordingTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        user = CustomUser.objects.create_user(
            username='m', email='m@example.com', password='x')
        self.student = Student.objects.create(user=user)

    def test_form_applies_labels_from_the_new_key(self):
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'field_messages': {
                'email': {'label': 'Your Email',
                          'help_text': '<b>required</b>'}}}})
        form = StudentProfileForm(student=self.student, request=None)
        self.assertEqual(form.fields['email'].label, 'Your Email')
        self.assertEqual(form.fields['email'].help_text, '<b>required</b>')

    def test_form_applies_labels_from_legacy_signup(self):
        Setting.objects.filter(key=student_profile.key).delete()
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'form_field_messages': json.dumps(
                {'email': {'label': 'Legacy Email'}})}})
        form = StudentProfileForm(student=self.student, request=None)
        self.assertEqual(form.fields['email'].label, 'Legacy Email')


class MigrationTests(TestCase):
    def setUp(self):
        self.module = importlib.import_module(
            'cis.migrations.0072_profile_field_messages')

    def test_moves_legacy_json_onto_student_profile(self):
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'intro': 'hi', 'form_field_messages':
                                json.dumps({'email': {'label': 'E'}})}})
        Setting.objects.update_or_create(
            key=student_profile.key, defaults={'value': {'field_weights': {}}})

        self.module.move_messages(global_apps, None)

        profile_value = Setting.objects.get(key=student_profile.key).value
        signup_value = Setting.objects.get(key=signup.key).value
        self.assertEqual(profile_value['field_messages'],
                         {'email': {'label': 'E'}})
        self.assertNotIn('form_field_messages', signup_value)
        self.assertEqual(signup_value['intro'], 'hi')

    def test_malformed_json_is_left_alone(self):
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'form_field_messages': '{not json'}})
        Setting.objects.update_or_create(
            key=student_profile.key, defaults={'value': {}})

        self.module.move_messages(global_apps, None)

        self.assertIn('form_field_messages',
                      Setting.objects.get(key=signup.key).value)
        self.assertNotIn('field_messages',
                         Setting.objects.get(key=student_profile.key).value)

    def test_no_rows_is_a_noop(self):
        Setting.objects.filter(
            key__in=[signup.key, student_profile.key]).delete()
        self.module.move_messages(global_apps, None)  # must not raise

    def test_unrecognised_keys_stay_on_signup(self):
        # `highschool_not_listed` is not a StudentProfileForm field, so the new
        # table has no row for it — moving it across would let the next Save
        # erase it. It stays behind instead.
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'intro': 'hi', 'form_field_messages':
                                json.dumps({
                                    'email': {'label': 'E'},
                                    'highschool_not_listed': {'label': 'HNL'},
                                    'field_dropped_last_year': {'label': 'X'},
                                })}})
        Setting.objects.update_or_create(
            key=student_profile.key, defaults={'value': {}})

        with self.assertLogs(self.module.logger, level='WARNING') as logs:
            self.module.move_messages(global_apps, None)

        warning = '\n'.join(logs.output)
        self.assertIn('highschool_not_listed', warning)
        self.assertIn('field_dropped_last_year', warning)

        profile_value = Setting.objects.get(key=student_profile.key).value
        self.assertEqual(profile_value['field_messages'],
                         {'email': {'label': 'E'}})

        signup_value = Setting.objects.get(key=signup.key).value
        self.assertEqual(
            json.loads(signup_value['form_field_messages']),
            {'highschool_not_listed': {'label': 'HNL'},
             'field_dropped_last_year': {'label': 'X'}})
        self.assertEqual(signup_value['intro'], 'hi')

    def test_running_twice_is_idempotent(self):
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'form_field_messages': json.dumps({
                'email': {'label': 'E'},
                'highschool_not_listed': {'label': 'HNL'},
            })}})
        Setting.objects.update_or_create(
            key=student_profile.key, defaults={'value': {}})

        with self.assertLogs(self.module.logger, level='WARNING'):
            self.module.move_messages(global_apps, None)
        first_profile = Setting.objects.get(key=student_profile.key).value
        first_signup = Setting.objects.get(key=signup.key).value

        with self.assertLogs(self.module.logger, level='WARNING'):
            self.module.move_messages(global_apps, None)

        self.assertEqual(
            Setting.objects.get(key=student_profile.key).value, first_profile)
        self.assertEqual(
            Setting.objects.get(key=signup.key).value, first_signup)

    def test_running_twice_is_idempotent_when_everything_is_recognised(self):
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'intro': 'hi', 'form_field_messages':
                                json.dumps({'email': {'label': 'E'}})}})
        Setting.objects.update_or_create(
            key=student_profile.key, defaults={'value': {}})

        self.module.move_messages(global_apps, None)
        self.module.move_messages(global_apps, None)  # no key left to move

        self.assertEqual(
            Setting.objects.get(key=student_profile.key).value['field_messages'],
            {'email': {'label': 'E'}})
        self.assertNotIn('form_field_messages',
                         Setting.objects.get(key=signup.key).value)

    def test_missing_student_profile_row_is_created(self):
        Setting.objects.filter(key=student_profile.key).delete()
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'form_field_messages':
                                json.dumps({'email': {'label': 'E'}})}})

        self.module.move_messages(global_apps, None)

        self.assertEqual(
            Setting.objects.get(key=student_profile.key).value,
            {'field_messages': {'email': {'label': 'E'}}})

    def test_reverse_merges_onto_leftover_signup_keys(self):
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'form_field_messages': json.dumps(
                {'highschool_not_listed': {'label': 'HNL'}})}})
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'field_messages': {'email': {'label': 'E'}}}})

        self.module.restore_messages(global_apps, None)

        signup_value = Setting.objects.get(key=signup.key).value
        self.assertEqual(
            json.loads(signup_value['form_field_messages']),
            {'highschool_not_listed': {'label': 'HNL'},
             'email': {'label': 'E'}})
        self.assertNotIn(
            'field_messages',
            Setting.objects.get(key=student_profile.key).value)

    def test_reverse_leaves_unparseable_signup_blob_alone(self):
        Setting.objects.update_or_create(
            key=signup.key,
            defaults={'value': {'form_field_messages': '{not json'}})
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'field_messages': {'email': {'label': 'E'}}}})

        with self.assertLogs(self.module.logger, level='WARNING'):
            self.module.restore_messages(global_apps, None)

        self.assertEqual(
            Setting.objects.get(key=signup.key).value['form_field_messages'],
            '{not json')
        self.assertEqual(
            Setting.objects.get(key=student_profile.key).value['field_messages'],
            {'email': {'label': 'E'}})

    def test_reverse_puts_it_back_as_json(self):
        Setting.objects.update_or_create(
            key=signup.key, defaults={'value': {'intro': 'hi'}})
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'field_messages': {'email': {'label': 'E'}}}})

        self.module.restore_messages(global_apps, None)

        signup_value = Setting.objects.get(key=signup.key).value
        self.assertEqual(json.loads(signup_value['form_field_messages']),
                         {'email': {'label': 'E'}})
        self.assertNotIn(
            'field_messages',
            Setting.objects.get(key=student_profile.key).value)


class SignupSettingTests(TestCase):
    def test_signup_form_no_longer_offers_form_field_messages(self):
        from cis.settings.signup import SettingForm as SignupSettingForm

        self.assertNotIn('form_field_messages', SignupSettingForm.base_fields)
        # The verify-email map stays put.
        self.assertIn('verify_form_field_messages',
                      SignupSettingForm.base_fields)
