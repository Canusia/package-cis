"""PT-43 — TechCenterStaffViewSet must be CIS/TechCenterStaff-only.

The CE API endpoint /ce/api/tech_center_staff/ exposes staff profile data.
The matching CE UI routes are gated on the 'ce' (CIS) role, but the DRF
viewset inherited only the global IsAuthenticated default, so any logged-in
user (e.g. a highschool_admin) could read it. These tests lock in that:

  - highschool_admin  -> 403 (denied)
  - ce (CIS)          -> 200 (allowed)
  - tech_center_staff -> 200 (allowed)
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

API_URL = '/ce/api/tech_center_staff/?format=json'


class TechCenterStaffViewSetAuthzTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for the duration
        # of this test case.
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
        # Roles are resolved from group membership via CustomUser.get_roles().
        ce_group, _ = Group.objects.get_or_create(name='ce')
        techstaff_group, _ = Group.objects.get_or_create(name='tech_center_staff')
        hsadmin_group, _ = Group.objects.get_or_create(name='highschool_admin')

        cls.ce_user = User.objects.create_user(
            username='ce_pt43', email='ce_pt43@example.com',
            password='x', first_name='Cee', last_name='Ee', is_staff=True,
        )
        cls.ce_user.groups.add(ce_group)

        cls.techstaff_user = User.objects.create_user(
            username='tcs_pt43', email='tcs_pt43@example.com',
            password='x', first_name='Tech', last_name='Staff', is_staff=True,
        )
        cls.techstaff_user.groups.add(techstaff_group)

        cls.hsadmin_user = User.objects.create_user(
            username='hsa_pt43', email='hsa_pt43@example.com',
            password='x', first_name='High', last_name='School',
        )
        cls.hsadmin_user.groups.add(hsadmin_group)

    def _client_for(self, user):
        # The cis LoginRequiredMiddleware uses request.user.is_authenticated
        # (set by SessionMiddleware/AuthenticationMiddleware), so DRF's
        # force_authenticate is not enough — do a real session login.
        client = APIClient(REMOTE_ADDR='127.0.0.1')
        client.force_login(user)
        return client

    def test_highschool_admin_is_forbidden(self):
        client = self._client_for(self.hsadmin_user)
        resp = client.get(API_URL)
        self.assertEqual(resp.status_code, 403)

    def test_ce_user_is_allowed(self):
        client = self._client_for(self.ce_user)
        resp = client.get(API_URL)
        self.assertEqual(resp.status_code, 200)

    def test_tech_center_staff_user_is_allowed(self):
        client = self._client_for(self.techstaff_user)
        resp = client.get(API_URL)
        self.assertEqual(resp.status_code, 200)
