"""PT-40: per-user consecutive-failure lockout + CAPTCHA enforcement."""
from django.test import TestCase
from django.contrib.auth import get_user_model

User = get_user_model()


class CustomUserLockoutHelpersTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='lock1', email='lock1@example.com', password='Right-pass-12',
            first_name='Lo', last_name='Ck',
        )

    def test_defaults(self):
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertFalse(self.user.account_locked)
        self.assertEqual(User.MAX_FAILED_LOGINS, 3)

    def test_register_failed_login_increments(self):
        self.user.register_failed_login()
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)
        self.assertFalse(self.user.account_locked)

    def test_third_failure_locks(self):
        for _ in range(3):
            self.user.register_failed_login()
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 3)
        self.assertTrue(self.user.account_locked)

    def test_reset_failed_login_clears_counter(self):
        self.user.register_failed_login()
        self.user.reset_failed_login()
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertFalse(self.user.account_locked)

    def test_unlock_clears_lock_and_counter(self):
        for _ in range(3):
            self.user.register_failed_login()
        self.user.unlock()
        self.user.refresh_from_db()
        self.assertFalse(self.user.account_locked)
        self.assertEqual(self.user.failed_login_attempts, 0)


from cis.email_backend import EmailAuthBackend


class EmailAuthBackendLockoutTests(TestCase):
    def setUp(self):
        self.backend = EmailAuthBackend()
        self.user = User.objects.create_user(
            username='be1', email='be1@example.com', password='Right-pass-12',
            first_name='Be', last_name='Ck',
        )

    def _auth(self, password):
        return self.backend.authenticate(
            None, username='be1@example.com', password=password)

    def test_correct_password_authenticates_and_resets(self):
        self.user.register_failed_login()  # 1 prior failure
        result = self._auth('Right-pass-12')
        self.assertEqual(result, self.user)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)

    def test_wrong_password_increments_and_returns_none(self):
        self.assertIsNone(self._auth('nope'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)
        self.assertFalse(self.user.account_locked)

    def test_three_wrong_passwords_lock_account(self):
        for _ in range(3):
            self.assertIsNone(self._auth('nope'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.account_locked)

    def test_locked_account_rejected_even_with_correct_password(self):
        for _ in range(3):
            self._auth('nope')
        # Now locked; correct password must NOT authenticate.
        self.assertIsNone(self._auth('Right-pass-12'))

    def test_unlock_then_correct_password_works(self):
        for _ in range(3):
            self._auth('nope')
        self.user.refresh_from_db()
        self.user.unlock()
        self.assertEqual(self._auth('Right-pass-12'), self.user)

    def test_unknown_email_returns_none_without_error(self):
        self.assertIsNone(
            self.backend.authenticate(None, username='nobody@example.com', password='x'))


from django.test import RequestFactory
from cis.forms.customuser import MyCELoginForm


class LoginFormCaptchaHostTests(TestCase):
    def _form_for_host(self, host):
        request = RequestFactory().get('/', HTTP_HOST=host)
        return MyCELoginForm(request)

    def test_captcha_enforced_on_canusiaplatform_host(self):
        form = self._form_for_host('ewu.stage.canusiaplatform.com')
        self.assertIn('captcha', form.fields)

    def test_captcha_enforced_on_arbitrary_public_host(self):
        form = self._form_for_host('ewu.example.edu')
        self.assertIn('captcha', form.fields)

    def test_captcha_skipped_on_localhost(self):
        form = self._form_for_host('127.0.0.1:8003')
        self.assertNotIn('captcha', form.fields)


from cis.admin.customuser import CustomUserAdmin
from django.contrib.admin.sites import AdminSite


class AdminUnlockActionTests(TestCase):
    def test_unlock_action_clears_lock_and_counter(self):
        u = User.objects.create_user(
            username='adm1', email='adm1@example.com', password='x',
            first_name='Ad', last_name='Min',
        )
        for _ in range(3):
            u.register_failed_login()
        u.refresh_from_db()
        self.assertTrue(u.account_locked)

        admin = CustomUserAdmin(User, AdminSite())
        admin.unlock_accounts(request=None, queryset=User.objects.filter(pk=u.pk))

        u.refresh_from_db()
        self.assertFalse(u.account_locked)
        self.assertEqual(u.failed_login_attempts, 0)
