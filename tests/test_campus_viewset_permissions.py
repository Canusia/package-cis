"""PT-44 (Medium) regression: CampusViewSet must be CIS-only.

`/ce/api/campus/` is the backend for the CIS-only `/ce/campuses/` page.
Before the fix it inherited DRF's default IsAuthenticated permission, so any
authenticated user (e.g. a highschool_admin) could read campus records.
These tests lock the fix: non-CIS roles get 403, CIS (`ce`) users get 200.

Run inside the container:
    docker exec -w /app/webapp django_web_ewu python manage.py \
        test cis.tests.test_campus_viewset_permissions -v 2
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

from cis.models.course import Campus

User = get_user_model()


class CampusViewSetPermissionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # (the request has no usable IP). Disconnect for the duration of the
        # test case, mirroring test_teacher_course_viewset_filters.py.
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
        # Roles are derived from group names (CustomUser.get_roles()).
        Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='highschool_admin')

        cls.ce_user = User.objects.create_user(
            username='ce_campus', email='ce_campus@example.com',
            password='x', first_name='C', last_name='E', is_staff=True,
        )
        cls.ce_user.groups.add(Group.objects.get(name='ce'))

        cls.hs_admin = User.objects.create_user(
            username='hs_campus', email='hs_campus@example.com',
            password='x', first_name='H', last_name='S',
        )
        cls.hs_admin.groups.add(Group.objects.get(name='highschool_admin'))

        cls.campus = Campus.objects.create(name='Cheney Campus', code='CHEN')

    def _client_for(self, user):
        # The cis LoginRequiredMiddleware checks request.user.is_authenticated,
        # so DRF force_authenticate is not enough — do a real session login.
        client = APIClient(REMOTE_ADDR='127.0.0.1')
        client.force_login(user)
        return client

    def test_highschool_admin_gets_403(self):
        client = self._client_for(self.hs_admin)
        resp = client.get('/ce/api/campus/?format=json')
        self.assertEqual(resp.status_code, 403)

    def test_ce_user_gets_200_and_sees_campus(self):
        client = self._client_for(self.ce_user)
        resp = client.get('/ce/api/campus/?format=json')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        rows = (payload['results']
                if isinstance(payload, dict) and 'results' in payload
                else payload)
        names = {r['name'] for r in rows}
        self.assertIn('Cheney Campus', names)
