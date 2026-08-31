"""Regression test for the tenant-configurable CSRF cookie name bug.

Every JavaScript helper added for the bulk-action / dangling-account delete
work reads ``window.CSRF_TOKEN`` (falling back to a cookie scan only when
absent). That global is set by ``cis/logged-base.html`` via Django's
``csrf_token`` context variable, which is correct regardless of what
``CSRF_COOKIE_NAME`` a given tenant configures (this deployment sets
``ewu_csrftoken``, not the Django default ``csrftoken``).

This test only proves the server-side half: that any page extending
``logged-base.html`` renders a non-empty ``window.CSRF_TOKEN`` for a logged
-in CE user. It cannot exercise the JavaScript cookie-fallback logic itself
-- that requires a browser and is not covered here.
"""
import re

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase

from cis.models import CustomUser


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class LoggedBaseCsrfTokenTests(TestCase):
    def setUp(self):
        self._saved_login_receivers = _disconnect_login_signal()

        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.ce_user = CustomUser.objects.create_superuser(
            username='csrftoken_ce', email='csrftoken_ce@example.com',
            password='x')
        self.ce_user.groups.add(ce_group)
        self.client.force_login(self.ce_user)

    def tearDown(self):
        _reconnect_login_signal(self._saved_login_receivers)

    def test_window_csrf_token_is_rendered_with_a_nonempty_value(self):
        """A CE page extending logged-base.html must expose a real,
        non-empty CSRF token via window.CSRF_TOKEN, independent of the
        CSRF_COOKIE_NAME this deployment happens to be configured with."""
        response = self.client.get('/ce/students/')
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        match = re.search(
            r'window\.CSRF_TOKEN\s*=\s*"([^"]*)"', content)
        self.assertIsNotNone(
            match, 'window.CSRF_TOKEN assignment not found in rendered page')
        self.assertTrue(
            match.group(1),
            'window.CSRF_TOKEN was rendered but is empty')
