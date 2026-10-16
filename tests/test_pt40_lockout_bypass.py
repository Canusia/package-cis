"""PT-40 lockout bypasses (package-cis#77).

1. A locked account refused by EmailAuthBackend must not fall through to
   another backend that checks the password without the lock. Django's plain
   ModelBackend did, on username + password; system check cis.W006 flags a
   tenant that still lists it.
2. Non-email usernames (/ce/ldap/) are counted and locked by EmailAuthBackend.
3. The lock check, password check and counter update run under a row lock, so
   parallel guesses cannot all get a password check before the lock is set.
4. MyCELoginForm says the same thing for an unknown email, a wrong password
   and a locked account.
5. A password reset through the emailed link clears the lock.
Minor: the Locked Accounts bulk unlock counts a duplicated id once.
"""
import json
import threading
from unittest import mock

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.tokens import default_token_generator
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection, connections
from django.test import (
    RequestFactory, TestCase, TransactionTestCase, override_settings,
    skipUnlessDBFeature,
)
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from cis.checks import PLAIN_MODEL_BACKEND, lockout_bypass_backend_check
from cis.email_backend import EmailAuthBackend
from cis.forms.customuser import MyCELoginForm

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

EMAIL_BACKEND = 'cis.email_backend.EmailAuthBackend'
SAML_BACKEND = 'cis.saml_backend.MyCE_SAMLAuthenticationBackend'
# The backends a tenant should list once it drops the plain ModelBackend.
SAFE_BACKENDS = [EMAIL_BACKEND, SAML_BACKEND]


def _request():
    return RequestFactory().post('/', REMOTE_ADDR='127.0.0.1')


# Axes is off so these exercise our lock alone: with it on, axes' own
# lockout would mask a backend that skips account_locked.
@override_settings(AXES_ENABLED=False, AUTHENTICATION_BACKENDS=SAFE_BACKENDS)
class FullStackLockoutTests(TestCase):
    """Through django.contrib.auth.authenticate(), i.e. every listed backend."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='fs1@example.com', email='fs1@example.com',
            password='Right-pass-12', first_name='Fu', last_name='Ll',
        )

    def test_locked_account_cannot_sign_in_via_any_backend(self):
        for _ in range(3):
            self.assertIsNone(authenticate(
                _request(), username='fs1@example.com', password='nope'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.account_locked)

        self.assertIsNone(authenticate(
            _request(), username='fs1@example.com', password='Right-pass-12'))

    def test_each_attempt_counts_once(self):
        authenticate(_request(), username='fs1@example.com', password='nope')
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)

    def test_right_password_signs_in_through_email_backend(self):
        user = authenticate(
            _request(), username='fs1@example.com', password='Right-pass-12')
        self.assertEqual(user, self.user)
        self.assertEqual(user.backend, EMAIL_BACKEND)


class LockoutBypassBackendCheckTests(TestCase):
    """cis.W006 flags a tenant that still lists django's plain ModelBackend."""

    @override_settings(AUTHENTICATION_BACKENDS=SAFE_BACKENDS + [PLAIN_MODEL_BACKEND])
    def test_warns_when_plain_model_backend_listed(self):
        ids = [m.id for m in lockout_bypass_backend_check(None)]
        self.assertEqual(ids, ['cis.W006'])

    @override_settings(AUTHENTICATION_BACKENDS=SAFE_BACKENDS)
    def test_silent_without_plain_model_backend(self):
        self.assertEqual(lockout_bypass_backend_check(None), [])

    @override_settings(AUTHENTICATION_BACKENDS=SAFE_BACKENDS + [PLAIN_MODEL_BACKEND])
    def test_plain_model_backend_really_bypasses_the_lock(self):
        # Pins why W006 exists: with ModelBackend listed, the right password
        # signs a locked account in on username.
        user = User.objects.create_user(
            username='byp@example.com', email='byp@example.com',
            password='Right-pass-12')
        for _ in range(3):
            user.register_failed_login()
        signed_in = authenticate(
            _request(), username='byp@example.com', password='Right-pass-12')
        self.assertEqual(signed_in, user)
        self.assertEqual(signed_in.backend, PLAIN_MODEL_BACKEND)


class UsernameLoginLockoutTests(TestCase):
    """/ce/ldap/ authenticates with a raw (non-email) username."""

    def setUp(self):
        self.backend = EmailAuthBackend()
        self.user = User.objects.create_user(
            username='plainname', email='pn@example.com',
            password='Right-pass-12', first_name='Pl', last_name='Ain',
        )

    def _auth(self, password, username='plainname'):
        return self.backend.authenticate(
            None, username=username, password=password)

    def test_username_signs_in(self):
        self.assertEqual(self._auth('Right-pass-12'), self.user)

    def test_username_failures_count_and_lock(self):
        for _ in range(3):
            self.assertIsNone(self._auth('nope'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.account_locked)
        self.assertIsNone(self._auth('Right-pass-12'))

    def test_email_and_username_share_one_counter(self):
        self._auth('nope')
        self._auth('nope', username='pn@example.com')
        self._auth('nope')
        self.user.refresh_from_db()
        self.assertTrue(self.user.account_locked)
        self.assertIsNone(self._auth('Right-pass-12', username='pn@example.com'))

    def test_unknown_username_returns_none(self):
        self.assertIsNone(self._auth('nope', username='nobody-here'))
        self.assertIsNone(self._auth('nope', username=''))
        self.assertIsNone(self._auth('nope', username=None))

    def test_ignores_other_backends_credentials(self):
        # authenticate(request, idp=..., saml=...) reaches this backend too
        # now that it accepts **kwargs; it must step aside quietly.
        self.assertIsNone(self.backend.authenticate(None, idp=object(), saml={}))

    def test_duplicate_email_falls_back_to_exact_username(self):
        User.objects.create_user(
            username='dup-other', email='PN@example.com', password='x')
        self.user.username = 'pn@example.com'
        self.user.save(update_fields=['username'])
        self.assertEqual(
            self._auth('Right-pass-12', username='pn@example.com'), self.user)


class LockUnderRowLockTests(TestCase):
    def test_attempt_takes_a_row_lock(self):
        user = User.objects.create_user(
            username='rl1', email='rl1@example.com', password='Right-pass-12')
        with CaptureQueriesContext(connection) as ctx:
            EmailAuthBackend().authenticate(
                None, username='rl1@example.com', password='nope')
        self.assertTrue(
            any('FOR UPDATE' in q['sql'] for q in ctx.captured_queries),
            'EmailAuthBackend must select_for_update() the user row')
        user.refresh_from_db()
        self.assertEqual(user.failed_login_attempts, 1)


@skipUnlessDBFeature('has_select_for_update')
class ParallelAttemptsTests(TransactionTestCase):
    """N concurrent wrong passwords get at most MAX_FAILED_LOGINS checks."""

    ATTEMPTS = 8

    def test_parallel_guesses_stop_at_the_threshold(self):
        user = User.objects.create_user(
            username='par1', email='par1@example.com', password='Right-pass-12')

        checks = []
        guard = threading.Lock()
        real_check = User.check_password

        def counting_check(self_, raw):
            with guard:
                checks.append(raw)
            return real_check(self_, raw)

        barrier = threading.Barrier(self.ATTEMPTS)

        def attempt():
            try:
                barrier.wait(timeout=10)
                EmailAuthBackend().authenticate(
                    None, username='par1@example.com', password='nope')
            finally:
                connections.close_all()

        with mock.patch.object(User, 'check_password', counting_check):
            threads = [threading.Thread(target=attempt) for _ in range(self.ATTEMPTS)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

        user.refresh_from_db()
        self.assertTrue(user.account_locked)
        self.assertEqual(user.failed_login_attempts, User.MAX_FAILED_LOGINS)
        self.assertEqual(len(checks), User.MAX_FAILED_LOGINS)


@override_settings(AUTHENTICATION_BACKENDS=SAFE_BACKENDS)
class LoginMessageTests(TestCase):
    """The failure message must not reveal whether an email is registered."""

    def _messages_for(self, email, password='nope'):
        request = RequestFactory().post('/', HTTP_HOST='127.0.0.1')
        SessionMiddleware(lambda r: None).process_request(request)
        request._messages = FallbackStorage(request)
        form = MyCELoginForm(
            request, data={'useremail': email, 'password': password})
        self.assertTrue(form.is_valid(), form.errors)
        form.save(request, 'login', 'logged_home')
        return [str(m) for m in get_messages(request)]

    def test_unknown_wrong_password_and_locked_get_the_same_message(self):
        User.objects.create_user(
            username='msg-open', email='msg-open@example.com',
            password='Right-pass-12')
        locked = User.objects.create_user(
            username='msg-locked', email='msg-locked@example.com',
            password='Right-pass-12')
        for _ in range(3):
            locked.register_failed_login()

        unknown = self._messages_for('nobody@example.com')
        self.assertEqual(len(unknown), 1)
        self.assertEqual(self._messages_for('msg-open@example.com'), unknown)
        self.assertEqual(self._messages_for('msg-locked@example.com'), unknown)
        # Even the right password on a locked account says nothing more.
        self.assertEqual(
            self._messages_for('msg-locked@example.com', 'Right-pass-12'), unknown)


class PasswordResetUnlocksTests(TestCase):
    @mock.patch('cis.views.password_management.send_mail')
    def test_reset_via_emailed_link_clears_lock(self, _send_mail):
        user = User.objects.create_user(
            username='rs1', email='rs1@example.com', password='Old-pass-12')
        for _ in range(3):
            user.register_failed_login()
        user.refresh_from_db()
        self.assertTrue(user.account_locked)

        url = reverse('password_reset_confirm', args=[
            urlsafe_base64_encode(force_bytes(user.pk)),
            default_token_generator.make_token(user),
        ])
        resp = self.client.post(url, {
            'new_password1': 'Brand-New-pass-34',
            'new_password2': 'Brand-New-pass-34',
        })
        self.assertEqual(resp.status_code, 302)

        user.refresh_from_db()
        self.assertFalse(user.account_locked)
        self.assertEqual(user.failed_login_attempts, 0)
        self.assertIsNone(user.account_locked_at)
        self.assertEqual(
            EmailAuthBackend().authenticate(
                None, username='rs1@example.com', password='Brand-New-pass-34'),
            user)

    def test_bad_token_leaves_lock(self):
        user = User.objects.create_user(
            username='rs2', email='rs2@example.com', password='Old-pass-12')
        for _ in range(3):
            user.register_failed_login()
        url = reverse('password_reset_confirm', args=[
            urlsafe_base64_encode(force_bytes(user.pk)), 'bad-token'])
        self.client.post(url, {
            'new_password1': 'Brand-New-pass-34',
            'new_password2': 'Brand-New-pass-34',
        })
        user.refresh_from_db()
        self.assertTrue(user.account_locked)


class LockedBulkUnlockDuplicateIdsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        ce, _ = Group.objects.get_or_create(name='ce')
        cls.manager = User.objects.create_user(
            username='dup_mgr', email='dup_mgr@example.com', password='x',
            first_name='Mo', last_name='Mgr', is_staff=True)
        cls.manager.groups.add(ce)
        cls.manager.campus = {'manage_staff_accounts': 'Yes'}
        cls.manager.save()
        cls.locked = User.objects.create_user(
            username='dup_locked', email='dup_locked@example.com', password='x',
            account_locked=True, failed_login_attempts=3)

    def test_duplicate_ids_counted_once(self):
        self.client.force_login(self.manager, backend=EMAIL_BACKEND)
        resp = self.client.post(reverse('cis:locked_users_bulk_action'), {
            'action': 'unlock',
            'ids[]': [self.locked.id, self.locked.id],
        }, REMOTE_ADDR='127.0.0.1')
        body = json.loads(resp.content)
        self.assertIn('1 account(s) unlocked', body['message'])
        self.assertIn('0 skipped', body['message'])
        self.locked.refresh_from_db()
        self.assertFalse(self.locked.account_locked)
        self.assertEqual(self.locked.failed_login_attempts, 0)
        self.assertIsNone(self.locked.account_locked_at)
