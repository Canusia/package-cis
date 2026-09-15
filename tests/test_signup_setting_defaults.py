"""signup.install() seeds the key its readers use (#17).

The default start_app / verify_email / complete_signup messages were written
under `error_message`, but the settings form, the tenant signup form and
student/views/utils.py all read `error_messages`, so a freshly installed tenant
got none of them. On the signup form that surfaced as "None" under the email
field for an address already on file.
"""
import json

from django.http import HttpRequest
from django.test import TestCase

from cis.settings.signup import signup


class SignupInstallDefaultsTests(TestCase):
    def test_install_seeds_error_messages_key(self):
        signup(HttpRequest()).install()  # as register_settings builds it
        value = signup.from_db()

        self.assertNotIn('error_message', value)
        messages = json.loads(value['error_messages'])
        self.assertIn('start_app', messages)
        self.assertIn('verify_email', messages)
        self.assertIn('complete_signup', messages)

    def test_settings_form_reads_the_same_key(self):
        self.assertIn('error_messages', signup.base_fields)
