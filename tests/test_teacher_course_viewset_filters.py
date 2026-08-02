"""Verify TeacherCourseViewSet honors course_id and cohort_id filters.

These filters are required by the course#instructors and cohort#instructors
AJAX DataTables (instructors_table_unification plan).
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

from cis.models.course import Cohort, Course, TeacherCourseCertificate
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherHighSchool

User = get_user_model()


class TeacherCourseViewSetFilterTests(TestCase):
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
        # CIS_user_only checks for the 'ce' group; instructor group also
        # commonly required by code that touches teacher records.
        Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='instructor')

        cls.staff = User.objects.create_user(
            username='staff_tcv', email='staff_tcv@example.com',
            password='x', first_name='S', last_name='T', is_staff=True,
        )
        cls.staff.groups.add(Group.objects.get(name='ce'))

        cls.cohort_a = Cohort.objects.create(name='AlphaCo', designator='ALC')
        cls.cohort_b = Cohort.objects.create(name='BetaCo', designator='BTC')

        cls.course_a = Course.objects.create(
            name='AlphaCourse', title='Alpha', cohort=cls.cohort_a,
            catalog_number='101', credit_hours=3,
        )
        cls.course_b = Course.objects.create(
            name='BetaCourse', title='Beta', cohort=cls.cohort_b,
            catalog_number='201', credit_hours=3,
        )

        cls.hs = HighSchool.objects.create(name='HS Alpha')
        teacher_user = User.objects.create_user(
            username='t1', email='t1@example.com',
            password='x', first_name='T', last_name='One',
        )
        cls.teacher = Teacher.objects.create(user=teacher_user)
        cls.ths = TeacherHighSchool.objects.create(
            teacher=cls.teacher, highschool=cls.hs, status='active',
        )

        cls.cert_a = TeacherCourseCertificate.objects.create(
            teacher_highschool=cls.ths, course=cls.course_a, status='active',
        )
        cls.cert_b = TeacherCourseCertificate.objects.create(
            teacher_highschool=cls.ths, course=cls.course_b, status='active',
        )

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')
        # The cis LoginRequiredMiddleware uses request.user.is_authenticated
        # (set by SessionMiddleware/AuthenticationMiddleware), so DRF's
        # force_authenticate is not enough — do a real session login.
        self.client.force_login(self.staff)

    def test_no_filter_returns_all(self):
        resp = self.client.get('/ce/api/teacher-course/?format=json')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        ids = {r['id'] for r in rows}
        self.assertIn(self.cert_a.id, ids)
        self.assertIn(self.cert_b.id, ids)

    def test_course_id_filter_returns_only_that_course(self):
        resp = self.client.get(
            f'/ce/api/teacher-course/?format=json&course_id={self.course_a.id}')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        ids = {r['id'] for r in rows}
        self.assertEqual(ids, {self.cert_a.id})

    def test_cohort_id_filter_returns_only_that_cohort(self):
        resp = self.client.get(
            f'/ce/api/teacher-course/?format=json&cohort_id={self.cohort_b.id}')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        ids = {r['id'] for r in rows}
        self.assertEqual(ids, {self.cert_b.id})
