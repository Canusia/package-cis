"""PT-42: the CE registration form-refresh AJAX must be CIS-only.

`/ce/add_new_ajax/` is shared across role portals and is NOT URL-gated in
ewu, so a highschool_admin session can POST `model=studentregistration`
and reach `manage_registration`. That view's `refresh_registration_form`
action renders `AddNewStudentRegistrationForm`, whose querysets are
unscoped (Term.objects.all(), HighSchool.objects.all(), and
ClassSection filtered by attacker-supplied term+highschool). The result
leaks cross-tenant high school / term / class-section UUIDs and labels.

The fix is a per-method CIS guard at the top of `manage_registration`.
These tests pin that behavior: non-CE -> house 403 JSON with no
form_html; CE -> not 403 (request is allowed to proceed).
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

ADD_NEW_AJAX_URL = '/ce/add_new_ajax/'


class PT42RegistrationRefreshAuthzTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler raises in tests
        # because the request has no usable IP. Disconnect for this case.
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
        # Roles are resolved via user.get_roles() -> [g.name for g in
        # self.groups.all()]. user_has_cis_role checks for the 'ce' group.
        Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='highschool_admin')

        cls.hs_admin = User.objects.create_user(
            username='hsadmin_pt42', email='hsadmin_pt42@example.com',
            password='x', first_name='H', last_name='A',
        )
        cls.hs_admin.groups.add(Group.objects.get(name='highschool_admin'))

        cls.ce = User.objects.create_user(
            username='ce_pt42', email='ce_pt42@example.com',
            password='x', first_name='C', last_name='E', is_staff=True,
        )
        cls.ce.groups.add(Group.objects.get(name='ce'))

    def _post_refresh(self):
        # Minimal payload mirroring the pentest exploit. The guard runs
        # before the form is built, so no real Term/HighSchool rows are
        # required to assert the 403 path.
        return self.client.post(
            ADD_NEW_AJAX_URL,
            data={
                'model': 'studentregistration',
                'action': 'refresh_registration_form',
                'ajax': '1',
                'student': '11111111-1111-1111-1111-111111111111',
                'term': '7f6f63d8-3d0b-4a21-b498-ac1895eaa18a',
                'highschool': 'bc9110c4-cc1a-4764-8abe-bc0c0eb998bf',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_highschool_admin_gets_403_and_no_metadata(self):
        self.client.force_login(self.hs_admin)
        resp = self._post_refresh()

        self.assertEqual(resp.status_code, 403)
        body = resp.json()
        self.assertEqual(body.get('status'), 'error')
        self.assertEqual(
            body.get('message'),
            'You are not authorized to perform this action.',
        )
        # Hard proof the cross-tenant metadata never rendered.
        self.assertNotIn('form_html', body)

    def test_ce_user_is_not_forbidden(self):
        self.client.force_login(self.ce)
        resp = self._post_refresh()

        # CE must pass the role guard. We only assert it is NOT the 403
        # the guard produces; downstream form handling (200 with form_html,
        # or a validation error) is out of scope for this authz test.
        self.assertNotEqual(resp.status_code, 403)
