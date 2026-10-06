"""package-cis#68: sanitize_db guards and pure scrubbers.

None of these tests sanitizes anything. The command tests are SimpleTestCase,
which fails on any database query, so a refusal is proven to happen before the
command touches the database. Faker is not needed (and not installed in most
tenant images): the scrubbers take any object with Faker's methods.
"""
import sys
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from cis import sanitize
from cis.management.commands import sanitize_db

DB_NAME = 'cis.management.commands.sanitize_db.get_database_name'


class StubFake:
    def email(self):
        return 'fake@example.com'

    def name(self):
        return 'Fake Name'

    def sentence(self, nb_words=6):
        return ' '.join(['lorem'] * nb_words)

    def numerify(self, pattern):
        return pattern.replace('#', '5')


def run_command():
    call_command('sanitize_db', stdout=StringIO(), stderr=StringIO())


class GuardTests(SimpleTestCase):
    def test_check_guards(self):
        self.assertIsNone(sanitize.check_guards('dev', 'ewu_sanitized'))
        self.assertIsNone(sanitize.check_guards('local', 'x_sanitized'))
        for deploy_type in ('production', 'staging', 'preview', None, ''):
            self.assertIn('DEPLOY_TYPE', sanitize.check_guards(deploy_type, 'ewu_sanitized'))
        for name in ('ewu', 'ewu_sanitized_old', '', None, 'sanitized'):
            self.assertIn('_sanitized', sanitize.check_guards('dev', name))

    @override_settings(DEPLOY_TYPE='production')
    def test_refuses_wrong_deploy_type_before_anything_else(self):
        with mock.patch(DB_NAME, return_value='ewu_sanitized'), \
                mock.patch.dict(sys.modules, {'faker': None}), \
                mock.patch.object(sanitize_db.Command, 'users') as users:
            with self.assertRaisesMessage(CommandError, "DEPLOY_TYPE='production'"):
                run_command()
        users.assert_not_called()

    @override_settings(DEPLOY_TYPE='dev')
    def test_refuses_database_not_named_sanitized(self):
        with mock.patch(DB_NAME, return_value='ewu'), \
                mock.patch.dict(sys.modules, {'faker': None}), \
                mock.patch.object(sanitize_db.Command, 'users') as users:
            with self.assertRaisesMessage(CommandError, "must end with '_sanitized'"):
                run_command()
        users.assert_not_called()

    @override_settings(DEPLOY_TYPE='dev')
    def test_refuses_without_faker(self):
        with mock.patch(DB_NAME, return_value='ewu_sanitized'), \
                mock.patch.dict(sys.modules, {'faker': None}), \
                mock.patch.object(sanitize_db.Command, 'users') as users:
            with self.assertRaisesMessage(CommandError, 'pip install faker'):
                run_command()
        users.assert_not_called()

    @override_settings(DEPLOY_TYPE='dev')
    def test_the_real_test_database_is_refused(self):
        # No patching: the test database's name does not end with _sanitized.
        with mock.patch.object(sanitize_db.Command, 'users') as users:
            with self.assertRaises(CommandError):
                run_command()
        users.assert_not_called()


class ScrubJsonTests(SimpleTestCase):
    def test_recursive_scrub(self):
        fake = StubFake()
        doc = {
            'recommender_name': 'Jane Real',
            'recommender_email': 'jane@school.org',
            'contact': {'cellphone': '555-123-4567', 'notes': 'reach me at jane@school.org'},
            'answers': [{'student_name': 'Sam Real'}, 'short'],
            'essay': 'This is a long free-text answer that clearly exceeds forty characters.',
            'guid': '0f8fad5b-d9cb-469f-a165-70867728950e',
            'email_date': '2026-01-02',
            'count': 3,
            'flag': True,
            'missing': None,
            'blank_name': '  ',
        }
        out = sanitize.scrub_json(doc, fake)
        self.assertEqual(out['recommender_name'], 'Fake Name')
        self.assertEqual(out['recommender_email'], 'fake@example.com')
        self.assertEqual(out['contact']['cellphone'], '(555)555-5555')
        self.assertEqual(out['contact']['notes'], 'fake@example.com')
        self.assertEqual(out['answers'], [{'student_name': 'Fake Name'}, 'short'])
        self.assertTrue(out['essay'].startswith('lorem'))
        # identifiers, dates, non-strings and blanks survive
        self.assertEqual(out['guid'], doc['guid'])
        self.assertEqual(out['email_date'], '2026-01-02')
        self.assertEqual((out['count'], out['flag'], out['missing'], out['blank_name']),
                         (3, True, None, '  '))
        self.assertEqual(doc['recommender_name'], 'Jane Real', 'input must not be mutated')

    def test_list_items_inherit_parent_key(self):
        out = sanitize.scrub_json({'guardian_name': ['A B', 'C D']}, StubFake())
        self.assertEqual(out, {'guardian_name': ['Fake Name', 'Fake Name']})


class BlankSecretsTests(SimpleTestCase):
    def test_blanks_secret_keys_and_counts_them(self):
        value = {
            'ethos': {'api_key': 'abc', 'client_id': 'cid', 'base_url': 'https://x'},
            'smtp': [{'smtp_password': 'pw', 'host': 'mail'}],
            'stripe_webhook_secret': 'whsec',
            'token_ttl': 3600,
            'Access-Key': 'AKIA',
            'enable_password_reset': True,
            'password_hint': '',
            'credentials': {'user': 'u'},
        }
        out, hits = sanitize.blank_secrets(value)
        self.assertEqual(hits, 6)
        self.assertEqual(out['ethos'], {'api_key': '', 'client_id': '', 'base_url': 'https://x'})
        self.assertEqual(out['smtp'], [{'smtp_password': '', 'host': 'mail'}])
        self.assertEqual((out['stripe_webhook_secret'], out['token_ttl'], out['Access-Key']),
                         ('', '', ''))
        # booleans and empty values are left alone; containers under secret keys are walked
        self.assertIs(out['enable_password_reset'], True)
        self.assertEqual(out['password_hint'], '')
        self.assertEqual(out['credentials'], {'user': 'u'})
        self.assertEqual(value['ethos']['api_key'], 'abc', 'input must not be mutated')

    def test_scalars_pass_through(self):
        self.assertEqual(sanitize.blank_secrets('secret'), ('secret', 0))
        self.assertEqual(sanitize.blank_secrets(None), (None, 0))


class EmbeddedEmailTests(SimpleTestCase):
    def test_stable_fake_per_address_and_kept_domains(self):
        text = 'Mail Ann@School.org or ann@school.org, cc ops@canusia.com and x@example.com.'
        out = sanitize.replace_embedded_emails(text)
        fake = sanitize.fake_email_for('ann@school.org')
        self.assertEqual(out, f'Mail {fake} or {fake}, cc ops@canusia.com and x@example.com.')

    def test_walks_json_and_honours_custom_keep_domain(self):
        doc = {'a': ['t@tenant.edu', {'b': 'c@other.com'}], 'n': 1}
        out = sanitize.replace_embedded_emails(doc, keep_domains=('@tenant.edu',))
        self.assertEqual(out, {'a': ['t@tenant.edu', {'b': sanitize.fake_email_for('c@other.com')}],
                               'n': 1})


class TargetRegistryTests(SimpleTestCase):
    def test_default_targets_use_known_kinds(self):
        for entry in sanitize.DEFAULT_COLUMNS:
            sanitize.validate_column_target(entry)

    def test_setting_and_registry_extend_defaults(self):
        with mock.patch.object(sanitize, '_extra_columns', []), \
                mock.patch.object(sanitize, '_extra_truncate', []):
            sanitize.register_columns([('pkg_thing', 'email', 'email')])
            sanitize.register_truncate(['pkg_log'])
            extra = {'columns': [('tenant_thing', 'note', 'lorem'), sanitize.DEFAULT_COLUMNS[0]],
                     'truncate': ['tenant_log', 'django_session']}
            columns = sanitize.column_targets(extra)
            truncate = sanitize.truncate_targets(extra)
        self.assertEqual(columns[-2:], [('pkg_thing', 'email', 'email'), ('tenant_thing', 'note', 'lorem')])
        self.assertEqual(len(columns), len(set(columns)))
        self.assertEqual(truncate[-2:], ['pkg_log', 'tenant_log'])
        self.assertEqual(truncate.count('django_session'), 1)

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            sanitize.column_targets({'columns': [('t', 'c', 'shred')]})
        with mock.patch.object(sanitize, '_extra_columns', []), self.assertRaises(ValueError):
            sanitize.register_columns([('t', 'c')])
