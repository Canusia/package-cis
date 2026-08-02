"""PT-7: /ce/api/campus_id/ must be restricted to CE (CIS) staff.

Instructor and faculty sessions must NOT be able to query StudentCampusID
records (and the nested student PII the serializer exposes) for arbitrary
students. The endpoint is consumed only by CE-admin portal pages, so non-CE
roles must receive 403.
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


class CampusIDPermissionTests(TestCase):
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
        for name in ('ce', 'faculty', 'instructor'):
            Group.objects.get_or_create(name=name)

        cls.ce_user = User.objects.create_user(
            username='ce1', email='ce1@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        cls.ce_user.groups.add(Group.objects.get(name='ce'))

        cls.faculty_user = User.objects.create_user(
            username='fac1', email='fac1@example.com', password='x',
            first_name='Fay', last_name='Faculty',
        )
        cls.faculty_user.groups.add(Group.objects.get(name='faculty'))

        cls.instructor_user = User.objects.create_user(
            username='inst1', email='inst1@example.com', password='x',
            first_name='Ina', last_name='Instructor',
        )
        cls.instructor_user.groups.add(Group.objects.get(name='instructor'))

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def test_instructor_is_forbidden(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/campus_id/?format=json')
        self.assertEqual(resp.status_code, 403)

    def test_faculty_is_forbidden(self):
        self.client.force_login(self.faculty_user)
        resp = self.client.get('/ce/api/campus_id/?format=json')
        self.assertEqual(resp.status_code, 403)

    def test_ce_staff_allowed(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get('/ce/api/campus_id/?format=json')
        self.assertEqual(resp.status_code, 200)
