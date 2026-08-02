"""PT-36 (Medium): Stored XSS in the school-counselor registration email
preview via unsanitized template rendering.

Vector:
    /ce/settings/show_preview/?setting=school_counselor_regis_email&field=email

Mitigation (shipped in package-setting v2026.2.5): every settings endpoint,
including `show_preview`, is gated behind `_user_can_manage_settings`
(CIS `ce` role or superuser). A non-CIS attacker can no longer reach the
preview to store/trigger the `<img onerror>` payload; only CIS staff — who
already author these email templates — can preview. Per the house decision,
the `|safe` rendering is intentionally left unchanged; access control is the
mitigation. This test locks that access control in for the exact PT-36 vector.
"""
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

# The exact PT-36 query string.
PT36_SETTING = 'school_counselor_regis_email'
PT36_FIELD = 'email'


class PT36SettingsPreviewCISOnlyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for the duration
        # of this test case (house convention).
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
        # `user_has_cis_role` checks for the 'ce' group; the attacker role
        # under test is 'highschool_admin' (a real non-CIS portal role).
        Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='highschool_admin')

        cls.cis_user = User.objects.create_user(
            username='ce_pt36', email='ce_pt36@example.com',
            password='x', first_name='C', last_name='E', is_staff=True,
        )
        cls.cis_user.groups.add(Group.objects.get(name='ce'))

        cls.hs_admin = User.objects.create_user(
            username='hsadmin_pt36', email='hsadmin_pt36@example.com',
            password='x', first_name='H', last_name='S',
        )
        cls.hs_admin.groups.add(Group.objects.get(name='highschool_admin'))

    def _preview_url(self):
        # reverse('setting:show_preview') -> /ce/settings/show_preview/
        return (
            f"{reverse('setting:show_preview')}"
            f"?setting={PT36_SETTING}&field={PT36_FIELD}"
        )

    def test_non_cis_highschool_admin_is_forbidden(self):
        """The exact PT-36 vector returns 403 for a non-CIS (highschool_admin)
        session — the attacker can never reach the preview."""
        self.client.force_login(self.hs_admin)
        resp = self.client.get(self._preview_url())
        self.assertEqual(
            resp.status_code, 403,
            msg=f"PT-36 vector must be 403 for highschool_admin, got "
                f"{resp.status_code}",
        )

    def test_anonymous_is_not_admitted(self):
        """An unauthenticated request must not be admitted to the preview
        (it is redirected to login or rejected — never a 200 render)."""
        resp = self.client.get(self._preview_url())
        self.assertNotEqual(
            resp.status_code, 200,
            msg="PT-36 vector must not render (200) for an anonymous user",
        )

    def test_cis_user_is_admitted_past_the_gate(self):
        """A CIS (`ce`) session passes the access-control gate. The view may
        return 200 (preview) or 400 (if the configurator isn't registered in
        the test DB), but it must NOT be the 403 produced by
        `_settings_forbidden()` — proving CIS is admitted while non-CIS is not.
        """
        self.client.force_login(self.cis_user)
        resp = self.client.get(self._preview_url())
        self.assertNotEqual(
            resp.status_code, 403,
            msg="CIS (ce) user must be admitted past the settings gate, "
                "but received 403",
        )
