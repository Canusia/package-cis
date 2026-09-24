"""CSRF_FAILURE_VIEW (package-cis#52): log why the check failed, show a friendly retry page.

With DEBUG off, Django's own `django.security.csrf` warning never reaches the pod
logs, so a 403 gave no clue whether the cookie was missing, the Referer was
stripped, or Origin was `null`.
"""
from django.test import Client, RequestFactory, TestCase, override_settings

from cis.views.csrf import csrf_failure

LOGGER = 'cis.views.csrf'


@override_settings(CSRF_FAILURE_VIEW='cis.views.csrf.csrf_failure')
class CsrfFailureViewTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_missing_cookie_is_logged_and_gets_the_friendly_page(self):
        with self.assertLogs(LOGGER, level='WARNING') as logs:
            resp = self.client.post('/?next=/student/', {'email': 'a@b.com'},
                                    HTTP_USER_AGENT='Chromebook/1.0')
        self.assertEqual(resp.status_code, 403)
        body = resp.content.decode()
        self.assertIn('Your session has expired', body)
        self.assertIn('href="/?next=/student/"', body)
        self.assertNotIn('CSRF verification failed', body)

        line = logs.output[0]
        self.assertIn("reason='CSRF cookie not set.'", line)
        self.assertIn('path=/ method=POST', line)
        self.assertIn('has_csrf_cookie=False', line)
        self.assertIn('has_session_cookie=False', line)
        self.assertIn("user_agent='Chromebook/1.0'", line)

    @override_settings(CSRF_COOKIE_NAME='ewu_csrftoken')
    def test_cookie_presence_uses_the_configured_cookie_name(self):
        self.client.cookies['ewu_csrftoken'] = 'x' * 32
        with self.assertLogs(LOGGER, level='WARNING') as logs:
            resp = self.client.post('/', {})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('has_csrf_cookie=True', logs.output[0])

    def test_origin_and_referer_are_logged(self):
        request = RequestFactory().post(
            '/student/verify/', HTTP_ORIGIN='null', HTTP_REFERER='https://x.test/a')
        with self.assertLogs(LOGGER, level='WARNING') as logs:
            resp = csrf_failure(request, reason='Origin checking failed - null does not match.')
        self.assertEqual(resp.status_code, 403)
        self.assertIn("origin='null'", logs.output[0])
        self.assertIn("referer='https://x.test/a'", logs.output[0])

    def test_retry_link_is_escaped(self):
        request = RequestFactory().post('/x/?a="><script>alert(1)</script>')
        with self.assertLogs(LOGGER, level='WARNING'):
            resp = csrf_failure(request, reason='CSRF token missing.')
        self.assertNotIn('<script>alert(1)</script>', resp.content.decode())

    def test_view_is_exempt_from_the_login_middleware(self):
        self.assertIs(csrf_failure.login_required, False)
