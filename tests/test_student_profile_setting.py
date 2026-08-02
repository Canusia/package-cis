from django.http import HttpRequest, QueryDict
from django.test import TestCase

from cis.models.settings import Setting
from cis.settings.student_profile import (
    student_profile,
    DEFAULT_LOCKED_MESSAGE,
    DEFAULT_EDITABLE_MESSAGE,
    DEFAULT_REVIEW_INTRO,
    DEFAULT_REVIEW_TEMPLATE,
)


class StudentProfileSettingTests(TestCase):

    def test_install_writes_defaults(self):
        Setting.objects.filter(key=student_profile.key).delete()

        student_profile(HttpRequest()).install()

        value = student_profile.from_db()
        self.assertEqual(value['locked_message'], DEFAULT_LOCKED_MESSAGE)
        self.assertEqual(value['editable_message'], DEFAULT_EDITABLE_MESSAGE)
        self.assertEqual(value['profile_review_intro'], DEFAULT_REVIEW_INTRO)
        self.assertEqual(value['profile_review_template'], DEFAULT_REVIEW_TEMPLATE)
        self.assertIsInstance(value['editable_fields'], list)
        self.assertIn('cell_phone', value['editable_fields'])

    def test_from_db_returns_empty_dict_when_missing(self):
        Setting.objects.filter(key=student_profile.key).delete()
        self.assertEqual(student_profile.from_db(), {})

    def test_to_python_returns_all_fields(self):
        # Order and editability POST through the one combined control
        # (profile_fields_*) but are stored under their own keys.
        data = QueryDict(mutable=True)
        data.update(
            {
                'profile_fields_weight_email': '10',
                'locked_message': 'Locked.',
                'editable_message': 'Editable.',
                'profile_review_intro': 'Intro.',
                'profile_review_template': '<div>{{ student.user.first_name }}</div>',
            }
        )
        data.setlist('profile_fields_editable', ['cell_phone', 'email'])

        form = student_profile(HttpRequest(), data=data)
        self.assertTrue(form.is_valid(), form.errors)
        result = form._to_python()
        self.assertEqual(result['editable_fields'], ['cell_phone', 'email'])
        self.assertEqual(result['field_weights'], {'email': 10})
        self.assertEqual(result['locked_message'], 'Locked.')
        self.assertEqual(
            result['profile_review_template'],
            '<div>{{ student.user.first_name }}</div>',
        )

    def test_invalid_template_is_rejected(self):
        form = student_profile(
            HttpRequest(),
            data={
                'locked_message': '',
                'editable_message': '',
                'profile_review_intro': '',
                'profile_review_template': '{% bad_tag %}',
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn('profile_review_template', form.errors)

    def test_editable_fields_rejects_unknown_field(self):
        data = QueryDict(mutable=True)
        data.update(
            {
                'locked_message': '',
                'editable_message': '',
                'profile_review_intro': '',
                'profile_review_template': '<div></div>',
            }
        )
        data.setlist('profile_fields_editable', ['not_a_real_field'])

        form = student_profile(HttpRequest(), data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('profile_fields', form.errors)


class ProfileFieldVocabularyTest(TestCase):
    """PROFILE_FIELDS is derived from the tenant form, not hand-maintained."""

    def test_profile_fields_is_the_form_minus_signup_mechanics(self):
        from cis.forms.student_profile import StudentProfileForm
        from cis.settings.student_profile import (
            SIGNUP_MECHANIC_FIELDS, profile_fields)
        self.assertEqual(
            profile_fields(),
            [n for n in StudentProfileForm.base_fields
             if n not in SIGNUP_MECHANIC_FIELDS])

    def test_profile_fields_uses_form_declaration_order(self):
        # The old literal parked these two at the end, out of step with the
        # weights default_field_weights() seeds from base_fields.
        from cis.settings.student_profile import profile_fields
        names = profile_fields()
        self.assertLess(names.index('start_date'), names.index('current_grade_level'))
        self.assertLess(names.index('graduation_date'), names.index('current_grade_level'))

    def test_message_fields_appends_signup_mechanics(self):
        from cis.settings.student_profile import (
            SIGNUP_MECHANIC_FIELDS, message_fields, profile_fields)
        self.assertEqual(
            message_fields(),
            profile_fields() + list(SIGNUP_MECHANIC_FIELDS))

    def test_hardcoded_constants_are_gone(self):
        import cis.settings.student_profile as mod
        self.assertFalse(hasattr(mod, 'PROFILE_FIELDS'))
        self.assertFalse(hasattr(mod, 'PROFILE_FIELD_CHOICES'))

    def test_install_seeds_editable_fields_from_the_tenant_module(self):
        from cis.forms.student_profile import tenant_editable_fields
        from cis.settings.student_profile import student_profile

        student_profile(HttpRequest()).install()
        stored = Setting.objects.get(key=student_profile.key).value
        self.assertEqual(stored['editable_fields'], list(tenant_editable_fields()))

    def test_default_weights_cover_the_whole_vocabulary(self):
        from cis.settings.student_profile import (
            default_field_weights, profile_field_names)
        weights = default_field_weights()
        self.assertEqual(sorted(weights), sorted(profile_field_names()))


class StudentProfileSettingRegistrationTests(TestCase):

    def test_setting_is_registered_in_configurators(self):
        from cis.apps import CisConfig
        names = [c['name'] for c in CisConfig.CONFIGURATORS]
        self.assertIn('student_profile', names)
