"""The signup `error_messages` field documents every key the code reads.

The value is free-form JSON, so a CE admin editing it has no other way to know
which keys exist. Anything reachable from student/views/onboarding.py or a
tenant's verify_email_form must appear in the field's help text; an undocumented
key is a message nobody knows they can set (#17).
"""
from django.http import HttpRequest
from django.test import TestCase

from cis.settings.signup import SIGNUP_ERROR_MESSAGE_KEYS, signup


class SignupErrorMessagesHelpTextTests(TestCase):
    EXPECTED = {
        'start_app': [
            'success', 'error', 'form_validation_fail',
            'dup_email.account_unverified',
            'dup_email.incomplete_application', 'dup_email.being_processed',
            'dup_email.pending_ernie_login',
            'dup_email.non_student_account_exists',
        ],
        'verify_email': ['invalid_token', 'account_already_verified', 'success'],
        'complete_signup': [
            'awaiting_processing_error', 'error', 'success',
            'form_validation_fail',
        ],
    }

    def test_documented_keys_match_the_keys_the_code_reads(self):
        documented = {
            section: [key for key, _desc in keys]
            for section, keys in SIGNUP_ERROR_MESSAGE_KEYS.items()
        }
        self.assertEqual(documented, self.EXPECTED)

    def test_help_text_lists_every_key(self):
        help_text = str(signup(HttpRequest()).fields['error_messages'].help_text)

        for section, keys in self.EXPECTED.items():
            self.assertIn(section, help_text)
            for key in keys:
                leaf = key.split('.')[-1]
                self.assertIn(leaf, help_text, msg=f'{section}.{key}')

    def test_help_text_still_says_the_value_is_json(self):
        help_text = str(signup(HttpRequest()).fields['error_messages'].help_text)
        self.assertIn('JSON', help_text)

    def test_every_documented_key_has_a_description(self):
        for section, keys in SIGNUP_ERROR_MESSAGE_KEYS.items():
            for key, description in keys:
                self.assertTrue(description.strip(), msg=f'{section}.{key}')

    def test_installed_defaults_cover_the_documented_keys(self):
        import json

        signup(HttpRequest()).install()
        defaults = json.loads(signup.from_db()['error_messages'])

        for section, keys in SIGNUP_ERROR_MESSAGE_KEYS.items():
            for key, _desc in keys:
                node = defaults.get(section, {})
                for part in key.split('.'):
                    self.assertIn(part, node, msg=f'{section}.{key} missing from defaults')
                    node = node[part]
