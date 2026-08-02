"""Field weights on the student_profile setting drive display order on both the
student profile form and the (spec-driven) student application."""
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.http import QueryDict
from django.test import TestCase

from cis.forms.application_form import SpecDrivenApplicationForm
from cis.forms.student_profile import StudentProfileForm
from cis.models import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student
from cis.settings.student_profile import (
    ProfileFieldsField,
    default_field_weights,
    order_field_names,
    profile_fields,
    student_profile,
)


class OrderFieldNamesTests(TestCase):
    def test_no_weights_is_a_noop(self):
        names = ['a', 'b', 'c']
        self.assertEqual(order_field_names(names, {}), names)

    def test_weights_reorder(self):
        names = ['a', 'b', 'c']
        self.assertEqual(
            order_field_names(names, {'a': 30, 'b': 20, 'c': 10}),
            ['c', 'b', 'a'])

    def test_unweighted_field_stays_anchored_after_its_predecessor(self):
        # 'b' has no weight, so it rides along right after 'a'.
        self.assertEqual(
            order_field_names(['a', 'b', 'c'], {'a': 20, 'c': 10}),
            ['c', 'a', 'b'])

    def test_equal_weights_break_ties_on_original_position(self):
        self.assertEqual(
            order_field_names(['a', 'b'], {'a': 10, 'b': 10}), ['a', 'b'])

    def test_non_numeric_weight_is_ignored(self):
        self.assertEqual(
            order_field_names(['a', 'b'], {'a': 'x', 'b': 5}), ['a', 'b'])

    def test_default_weights_preserve_declared_order(self):
        weights = default_field_weights()
        declared = list(StudentProfileForm.base_fields)
        self.assertEqual(
            order_field_names(declared, weights),
            order_field_names(declared, {}))


class ProfileFieldsFieldTests(TestCase):
    def test_cleans_strings_to_ints(self):
        self.assertEqual(
            ProfileFieldsField().clean(
                {'weights': {'first_name': '20', 'email': 10},
                 'editable': ['email']}),
            {'weights': {'first_name': 20, 'email': 10},
             'editable': ['email'], 'messages': {}})

    def test_rejects_non_numeric(self):
        with self.assertRaises(Exception):
            ProfileFieldsField().clean({'weights': {'first_name': 'abc'}})

    def test_widget_renders_draggable_rows_and_loads_its_script(self):
        html = ProfileFieldsField().widget.render(
            'profile_fields', {'weights': {'first_name': 10}})
        self.assertIn('class="table table-sm mb-0 field-weights-table"', html)
        self.assertIn('<tr draggable="true" data-field="first_name">', html)
        self.assertIn('js/field_weights.js', html)

    def test_widget_renders_one_row_per_field_with_both_controls(self):
        html = ProfileFieldsField().widget.render('profile_fields', {})
        self.assertEqual(html.count('<tr draggable='), len(profile_fields()))
        self.assertEqual(html.count('name="profile_fields_editable"'),
                         len(profile_fields()))
        self.assertEqual(html.count('name="profile_fields_weight_'),
                         len(profile_fields()))

    def test_widget_checks_editable_fields(self):
        html = ProfileFieldsField().widget.render(
            'profile_fields', {'editable': ['email']})
        self.assertIn('name="profile_fields_editable" value="email" checked',
                      html)
        self.assertIn(
            'name="profile_fields_editable" value="first_name">', html)

    def test_widget_rows_follow_weight_order(self):
        html = ProfileFieldsField().widget.render(
            'profile_fields', {'weights': {'first_name': 90, 'email': 1}})
        self.assertLess(html.index('data-field="email"'),
                        html.index('data-field="first_name"'))

    def test_widget_reads_checkboxes_and_skips_blank_weights(self):
        widget = ProfileFieldsField().widget
        data = QueryDict(mutable=True)
        data.update({'profile_fields_weight_first_name': '20',
                     'profile_fields_weight_last_name': ''})
        data.setlist('profile_fields_editable', ['email'])
        value = widget.value_from_datadict(data, {}, 'profile_fields')
        self.assertEqual(value, {'weights': {'first_name': '20'},
                                 'editable': ['email'], 'messages': {}})

    def test_rejects_unknown_editable_field(self):
        # Only reachable via a tampered POST — the checkboxes are server-rendered.
        with self.assertRaises(Exception):
            ProfileFieldsField().clean({'editable': ['not_a_real_field']})


class FormOrderingTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        user = CustomUser.objects.create_user(
            username='w', email='w@example.com', password='x')
        self.student = Student.objects.create(user=user)

    def _set_weights(self, weights):
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {'field_weights': weights}})

    def test_profile_form_respects_weights(self):
        self._set_weights({'email': 1, 'first_name': 2})
        form = StudentProfileForm(student=self.student, request=None)
        names = list(form.fields)
        # email is declared after first_name; the weights flip them (fields
        # declared next to email, e.g. password, ride along with it).
        self.assertEqual(names[0], 'email')
        self.assertLess(names.index('email'), names.index('first_name'))

    def test_profile_form_unchanged_without_weights(self):
        Setting.objects.filter(key=student_profile.key).delete()
        form = StudentProfileForm(student=self.student, request=None)
        self.assertEqual(list(form.fields), list(StudentProfileForm.base_fields))

    def test_application_form_reuses_profile_weights(self):
        self._set_weights({'zzz_last': 90, 'aaa_first': 10})
        spec = [
            {'name': 'zzz_last', 'type': 'text', 'label': 'Z',
             'required': False, 'target': 'meta'},
            {'name': 'aaa_first', 'type': 'text', 'label': 'A',
             'required': False, 'target': 'meta'},
        ]
        form = SpecDrivenApplicationForm(
            spec=spec, student=self.student, request=None)
        self.assertEqual(list(form.fields), ['aaa_first', 'zzz_last'])

    def test_spec_entry_weight_overrides_setting(self):
        self._set_weights({'zzz_last': 90, 'aaa_first': 10})
        spec = [
            {'name': 'zzz_last', 'type': 'text', 'label': 'Z', 'weight': 1,
             'required': False, 'target': 'meta'},
            {'name': 'aaa_first', 'type': 'text', 'label': 'A',
             'required': False, 'target': 'meta'},
        ]
        form = SpecDrivenApplicationForm(
            spec=spec, student=self.student, request=None)
        self.assertEqual(list(form.fields), ['zzz_last', 'aaa_first'])


class SettingRoundTripTests(TestCase):
    """The one combined control still reads and writes the two storage keys."""

    def _form(self, **kwargs):
        import types
        request = types.SimpleNamespace(GET={'report_id': '1'})
        return student_profile(request, **kwargs)

    def test_initial_folds_stored_keys_into_the_combined_control(self):
        form = self._form(initial={'editable_fields': ['email'],
                                   'field_weights': {'email': 10}})
        self.assertEqual(form.initial['profile_fields'],
                         {'editable': ['email'], 'weights': {'email': 10},
                          'messages': {}})
        html = form['profile_fields'].as_widget()
        self.assertIn('value="email" checked', html)

    def test_post_splits_back_into_editable_fields_and_field_weights(self):
        data = QueryDict(mutable=True)
        data.update({
            'profile_fields_weight_first_name': '5',
            'profile_fields_weight_email': '1',
            'locked_message': 'a', 'editable_message': 'b',
            'profile_review_intro': 'c',
            'profile_review_template': '<p>x</p>', 'profile_display': '',
        })
        data.setlist('profile_fields_editable', ['email', 'cell_phone'])

        form = self._form(data=data)
        self.assertTrue(form.is_valid(), form.errors.as_text())
        stored = form._to_python()
        self.assertEqual(stored['field_weights'], {'first_name': 5, 'email': 1})
        self.assertEqual(stored['editable_fields'], ['email', 'cell_phone'])

    def test_unchecking_everything_stores_an_empty_editable_list(self):
        # An empty list is honored downstream (nothing editable); only a
        # missing setting row falls back to the default editable set.
        data = QueryDict(mutable=True)
        data.update({'locked_message': '', 'editable_message': '',
                     'profile_review_intro': '',
                     'profile_review_template': '', 'profile_display': ''})
        form = self._form(data=data)
        self.assertTrue(form.is_valid(), form.errors.as_text())
        self.assertEqual(form._to_python()['editable_fields'], [])


class InstallTests(TestCase):
    def test_install_seeds_weights(self):
        Setting.objects.filter(key=student_profile.key).delete()
        with patch('cis.settings.student_profile.student_profile.__init__',
                   return_value=None):
            student_profile().install()
        value = Setting.objects.get(key=student_profile.key).value
        self.assertEqual(value['field_weights'], default_field_weights())
