"""Regression authz tests for the highschool-teacher DRF endpoint (PT-8).

PT-8's primary fix lives in cis.views.ajax.add_new (teacherhighschool branch,
tested in test_teacherhighschool_authz.py). This file pins the *other* surface
that carries the directive's "highschoolteacher" name: the DRF
HighSchoolTeacherViewSet, router key 'highschool-teacher', mounted at
/ce/api/highschool-teacher/ (cis.urls router under the /ce/ include).

The viewset is a ReadOnlyModelViewSet with permission_classes=[CIS_user_only],
so it must:
  * reject all write verbs (POST/PUT/PATCH/DELETE) for everyone, and
  * reject reads from a highschool_admin (non-CE) caller.

These tests guard against a future refactor accidentally making this endpoint
writable or non-CE-reachable, which would re-open the privilege escalation
(creating a TeacherHighSchool elevates the teacher's user into the
'instructor' group via TeacherHighSchool.save).
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

from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherHighSchool

User = get_user_model()

ENDPOINT = '/ce/api/highschool-teacher/'


class HighSchoolTeacherViewSetAuthzTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for this test case.
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
        # 'ce' is required by CIS_user_only; 'instructor' is needed because
        # TeacherHighSchool.save() adds the teacher's user to it.
        for name in ('ce', 'highschool_admin', 'instructor'):
            Group.objects.get_or_create(name=name)

        cls.hs = HighSchool.objects.create(name='HS Alpha')

        teacher_user = User.objects.create_user(
            username='target_teacher_vs', email='target_teacher_vs@example.com',
            password='x', first_name='Terry', last_name='Teacher',
        )
        cls.teacher = Teacher.objects.create(user=teacher_user)

        ce = User.objects.create_user(
            username='ce_vs', email='ce_vs@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        hsa = User.objects.create_user(
            username='hsa_vs', email='hsa_vs@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

    def setUp(self):
        # cis.middleware.LoginRequiredMiddleware gates every view on
        # request.user.is_authenticated (a *session* check), redirecting
        # anonymous sessions to LOGIN_URL with a 302 before DRF's permission
        # layer ever runs. DRF's force_authenticate only sets the user at the
        # view layer, so it is not enough here — we must establish a real
        # session via force_login (mirrors test_teacher_course_viewset_filters).
        # REMOTE_ADDR keeps any IP-dependent login signal handlers happy.
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def _write_payload(self):
        return {
            'teacher': str(self.teacher.id),
            'highschool': str(self.hs.id),
            'status': 'In the Program',
        }

    def test_highschool_admin_cannot_read(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(ENDPOINT)
        # Session-authenticated (passes the middleware), then rejected by
        # DRF's CIS_user_only permission because highschool_admin is not 'ce'.
        self.assertIn(resp.status_code, (401, 403))

    def test_ce_can_read(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get(ENDPOINT)
        self.assertEqual(resp.status_code, 200)

    def test_post_is_not_allowed_even_for_ce(self):
        # Read-only viewset: POST must be 405 (method not allowed), and must
        # NOT create a TeacherHighSchool.
        self.client.force_login(self.ce_user)
        resp = self.client.post(ENDPOINT, self._write_payload(), format='json')
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(TeacherHighSchool.objects.count(), 0)

    def test_post_rejected_for_highschool_admin(self):
        # highschool_admin must be blocked by permission (403/401) before any
        # write could occur; either way, no record is created.
        self.client.force_login(self.hsadmin_user)
        resp = self.client.post(ENDPOINT, self._write_payload(), format='json')
        self.assertIn(resp.status_code, (401, 403, 405))
        self.assertEqual(TeacherHighSchool.objects.count(), 0)
