"""The signup message catalog: message() resolution and install() seeding.

The reported symptom was a student re-applying with an address already on an
abandoned account and getting the literal text "None" as the error. Two
defects combined: install() seeded the key `error_message` (singular) while
every reader looks up `error_messages` (plural), so the whole catalog was
unreachable, and there was no message at all for the commonest dead end.

The duplicate-email branch that consumes these messages lives in each tenant's
`myce_tenant_configs.services.verify_email_form`, so its tests live there too.
"""
import json

from django.http import HttpRequest
from django.test import TestCase

from cis.models.settings import Setting
from cis.settings.signup import DEFAULT_MESSAGES, message, signup


class SignupMessageCatalogTests(TestCase):
    """message() must never hand a None to a student-facing renderer."""

    def setUp(self):
        Setting.objects.filter(key=signup.key).delete()

    def test_falls_back_when_setting_row_is_absent(self):
        self.assertEqual(
            message('verify_email', 'invalid_token'),
            DEFAULT_MESSAGES['verify_email']['invalid_token'],
        )

    def test_falls_back_when_catalog_key_is_missing(self):
        # The exact production shape: install() seeded 'error_message'
        # (singular) while every reader looks up 'error_messages' (plural).
        Setting.objects.create(
            key=signup.key, value={'error_message': json.dumps(DEFAULT_MESSAGES)})
        self.assertEqual(
            message('start_app', 'incomplete_application', subsection='dup_email'),
            DEFAULT_MESSAGES['start_app']['dup_email']['incomplete_application'],
        )

    def test_falls_back_on_malformed_json(self):
        Setting.objects.create(
            key=signup.key, value={'error_messages': 'not json at all {'})
        self.assertEqual(
            message('start_app', 'success'),
            DEFAULT_MESSAGES['start_app']['success'],
        )

    def test_falls_back_on_partial_tenant_catalog(self):
        # A tenant whose JSON predates a key still gets real text for it.
        Setting.objects.create(key=signup.key, value={
            'error_messages': json.dumps({'verify_email': {'success': 'Custom!'}}),
        })
        self.assertEqual(message('verify_email', 'success'), 'Custom!')
        self.assertEqual(
            message('verify_email', 'invalid_token'),
            DEFAULT_MESSAGES['verify_email']['invalid_token'],
        )

    def test_tenant_value_wins_over_default(self):
        Setting.objects.create(key=signup.key, value={
            'error_messages': json.dumps(
                {'start_app': {'dup_email': {'being_processed': 'Tenant text'}}}),
        })
        self.assertEqual(
            message('start_app', 'being_processed', subsection='dup_email'),
            'Tenant text',
        )

    def test_tenant_catalog_stored_already_decoded_is_honoured(self):
        # Setting.value is a JSONField, so error_messages can be stored as an
        # object rather than a JSON string. json.loads() on that dict raised
        # TypeError, which was caught and silently threw away every message
        # the tenant had customised.
        Setting.objects.create(key=signup.key, value={
            'error_messages': {'verify_email': {'success': 'Custom!'}},
        })
        self.assertEqual(message('verify_email', 'success'), 'Custom!')
        self.assertEqual(
            message('verify_email', 'invalid_token'),
            DEFAULT_MESSAGES['verify_email']['invalid_token'],
        )

    def test_unknown_key_is_none_not_an_exception(self):
        self.assertIsNone(message('start_app', 'no_such_key'))

    # error_messages is free-text JSON a tenant edits by hand, so "valid JSON
    # of the wrong shape" is a live possibility. Every one of these used to
    # raise AttributeError out of a .get() and 500 the signup page -- taking
    # the fallback down with it, which is the one thing message() promises.

    def test_falls_back_when_the_catalog_is_a_list(self):
        Setting.objects.create(
            key=signup.key, value={'error_messages': json.dumps(['nope'])})
        self.assertEqual(
            message('start_app', 'success'),
            DEFAULT_MESSAGES['start_app']['success'],
        )

    def test_falls_back_when_a_section_holds_a_string(self):
        Setting.objects.create(key=signup.key, value={
            'error_messages': json.dumps({'start_app': 'just some text'}),
        })
        self.assertEqual(
            message('start_app', 'success'),
            DEFAULT_MESSAGES['start_app']['success'],
        )

    def test_falls_back_when_a_subsection_holds_a_string(self):
        Setting.objects.create(key=signup.key, value={
            'error_messages': json.dumps(
                {'start_app': {'dup_email': 'just some text'}}),
        })
        self.assertEqual(
            message('start_app', 'being_processed', subsection='dup_email'),
            DEFAULT_MESSAGES['start_app']['dup_email']['being_processed'],
        )

    def test_falls_back_when_the_message_itself_is_not_a_string(self):
        # A nested object here would otherwise render as "{'a': 'b'}".
        Setting.objects.create(key=signup.key, value={
            'error_messages': json.dumps({'start_app': {'success': {'a': 'b'}}}),
        })
        self.assertEqual(
            message('start_app', 'success'),
            DEFAULT_MESSAGES['start_app']['success'],
        )


class SignupInstallTests(TestCase):
    """install() must not undo the catalog repair.

    It assigned setting.value unconditionally, so anything that re-ran it over
    an existing row overwrote every stored message -- a tenant's own wording
    and the repair myce_tenant_configs.0001_ewu_signup_message_catalog
    performs. register_settings only calls install() when the SettingRecord is
    missing, which makes that a narrow window rather than a routine one, but
    the whole message catalog now hangs off this key.
    """

    def setUp(self):
        Setting.objects.filter(key=signup.key).delete()

    def _install(self):
        # How register_settings does it: construct with a request, then
        # install() (setting/management/commands/register_settings.py).
        signup(HttpRequest()).install()

    def test_install_seeds_a_missing_row(self):
        self._install()
        stored = Setting.objects.get(key=signup.key).value
        self.assertEqual(json.loads(stored['error_messages']), DEFAULT_MESSAGES)

    def test_install_preserves_an_edited_catalog(self):
        tenant = {'start_app': {'success': 'Tenant wording'}}
        Setting.objects.create(
            key=signup.key, value={'error_messages': json.dumps(tenant)})

        self._install()

        stored = Setting.objects.get(key=signup.key).value
        self.assertEqual(json.loads(stored['error_messages']), tenant)
        self.assertEqual(message('start_app', 'success'), 'Tenant wording')

    def test_install_still_fills_in_keys_the_row_is_missing(self):
        Setting.objects.create(
            key=signup.key, value={'error_messages': json.dumps({})})

        self._install()

        stored = Setting.objects.get(key=signup.key).value
        self.assertEqual(stored['signup_terms'],
                         'Change this in Settings -> Students -> Signup Page')


