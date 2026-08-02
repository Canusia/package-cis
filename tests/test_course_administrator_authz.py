"""Authorization tests for the course_administrator add_new_ajax branch (PT-26).

Posting model=course_administrator to /ce/add_new_ajax/ must only succeed for
the 'ce' (CE administrator) role. A highschool_admin (or any other non-CE role)
must receive 403 and create no CourseAdministrator record. This guards the
manage_course_administrator_role handler in cis/views/course.py.
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

from cis.models.course import Cohort, Course, CourseAdministrator

User = get_user_model()


class CourseAdministratorAuthzTests(TestCase):
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
        for name in ('ce', 'faculty', 'highschool_admin', 'instructor', 'student'):
            Group.objects.get_or_create(name=name)

        cls.url = reverse('cis:add_new_ajax')

        cls.cohort = Cohort.objects.create(name='AdminCo', designator='ADC')
        cls.course = Course.objects.create(
            name='AdminCourse', title='Admin', cohort=cls.cohort,
            catalog_number='301', credit_hours=3,
        )

        # CE administrator (the only role allowed to manage course admins).
        ce = User.objects.create_user(
            username='ce_pt26', email='ce_pt26@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        # The user who will be assigned the CE course-administrator role.
        # Must be in ce/faculty for the form's `user` queryset to accept them.
        assignee = User.objects.create_user(
            username='assignee_pt26', email='assignee_pt26@example.com',
            password='x', first_name='Adam', last_name='Assignee',
        )
        assignee.groups.add(Group.objects.get(name='faculty'))
        cls.assignee = assignee

        # Highschool admin — the role used in the pentest exploit.
        hsa = User.objects.create_user(
            username='hsa_pt26', email='hsa_pt26@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def _post_data(self):
        return {
            'model': 'course_administrator',
            'id': '-1',
            'course': str(self.course.id),
            'user': str(self.assignee.id),
            'role': 'Administrator',
            'status': 'Active',
            'ajax': '1',
        }

    def test_highschool_admin_cannot_create_course_administrator(self):
        before = CourseAdministrator.objects.count()
        self.client.force_login(self.hsadmin_user)
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(CourseAdministrator.objects.count(), before)
        self.assertFalse(
            CourseAdministrator.objects.filter(user=self.assignee).exists())

    def test_highschool_admin_cannot_prefill_form(self):
        # The GET branch prefills the role-management form for any course/admin
        # pk; it must also be CE-only.
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(
            self.url,
            {
                'model': 'course_administrator',
                'id': '-1',
                'parent': str(self.course.id),
                'ajax': '1',
            })
        self.assertEqual(resp.status_code, 403)

    def test_ce_can_create_course_administrator(self):
        self.client.force_login(self.ce_user)
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')
        self.assertTrue(
            CourseAdministrator.objects.filter(
                course=self.course, user=self.assignee,
                role='Administrator').exists())
