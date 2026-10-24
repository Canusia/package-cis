"""Tenant switches for hard-coded login behaviour (#92, #114 item 4):
ACCOUNT_LOCKOUT_ENABLED / ACCOUNT_LOCKOUT_THRESHOLD, LOGIN_EXEMPT_VIEWS and
@login_exempt, and CSP_REPORT_ONLY_POLICY. Defaults are unchanged."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from cis.email_backend import EmailAuthBackend
from cis.middleware import (
    CspReportOnlyMiddleware, DEFAULT_CSP_REPORT_ONLY_POLICY,
    LoginRequiredMiddleware, login_exempt,
)

User = get_user_model()


class LockoutSettingsTests(TestCase):
    def setUp(self):
        self.backend = EmailAuthBackend()
        self.user = User.objects.create_user(
            username='cfg1', email='cfg1@example.com', password='Right-pass-12')

    def _auth(self, password):
        return self.backend.authenticate(
            None, username='cfg1@example.com', password=password)

    def test_default_threshold_is_three(self):
        self.assertEqual(User.lockout_threshold(), 3)
        self.assertTrue(User.lockout_enabled())

    @override_settings(ACCOUNT_LOCKOUT_THRESHOLD=5)
    def test_threshold_setting(self):
        for _ in range(4):
            self._auth('wrong')
        self.user.refresh_from_db()
        self.assertFalse(self.user.account_locked)
        self._auth('wrong')
        self.user.refresh_from_db()
        self.assertTrue(self.user.account_locked)

    @override_settings(ACCOUNT_LOCKOUT_ENABLED=False)
    def test_disabled_does_not_count_or_lock(self):
        for _ in range(5):
            self.assertIsNone(self._auth('wrong'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertFalse(self.user.account_locked)
        self.assertEqual(self._auth('Right-pass-12'), self.user)

    @override_settings(ACCOUNT_LOCKOUT_ENABLED=False)
    def test_disabled_does_not_refuse_an_old_lock(self):
        for _ in range(3):
            self.user.register_failed_login()
        self.assertEqual(self._auth('Right-pass-12'), self.user)


def _protected(request):
    return HttpResponse('ok')


def ExemptByName(request):
    return HttpResponse('ok')


class LoginExemptionTests(SimpleTestCase):
    def _process(self, view):
        request = RequestFactory().get('/x')
        request.user = AnonymousUser()
        request._messages = type('M', (), {'add': lambda *a, **k: None})()
        return LoginRequiredMiddleware(lambda r: None).process_view(request, view, (), {})

    def test_unknown_view_redirects(self):
        self.assertEqual(self._process(_protected).status_code, 302)

    @override_settings(LOGIN_EXEMPT_VIEWS=['ExemptByName'])
    def test_setting_adds_exemptions(self):
        self.assertIsNone(self._process(ExemptByName))

    def test_default_list_still_applies(self):
        def TermViewSet(request):
            return HttpResponse('ok')
        self.assertIsNone(self._process(TermViewSet))

    def test_login_exempt_decorator(self):
        @login_exempt
        def callback(request):
            return HttpResponse('ok')
        self.assertIsNone(self._process(callback))

    def test_login_exempt_on_a_class(self):
        from django.views import View

        @login_exempt
        class Callback(View):
            def get(self, request):
                return HttpResponse('ok')
        self.assertIsNone(self._process(Callback.as_view()))


class CspPolicyTests(SimpleTestCase):
    def _header(self):
        mw = CspReportOnlyMiddleware(lambda r: HttpResponse('ok'))
        return mw(RequestFactory().get('/'))['Content-Security-Policy-Report-Only']

    def test_default_policy(self):
        self.assertEqual(self._header(), DEFAULT_CSP_REPORT_ONLY_POLICY)

    @override_settings(CSP_REPORT_ONLY_POLICY="default-src 'self'")
    def test_tenant_policy(self):
        self.assertEqual(self._header(), "default-src 'self'")
