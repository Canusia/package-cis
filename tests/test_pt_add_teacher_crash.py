"""Regression test for the Future Sections add-teacher 500 crash.

Production traceback:
    File ".../future_sections/views/api.py", line 360, in add_teacher
        if record.teacher_course.status in fs_config.get(...):
    AttributeError: 'bool' object has no attribute 'teacher_course'

Cause: AddNewTeacherForm.save() returns False when the new teacher cannot be
created (Teacher.get_or_add -> None). The view then dereferences the bool.

This test drives that exact failure path (the "teacher not listed" branch with
no 'instructor' Group present, which makes Teacher.get_or_add return None) and
asserts the endpoint returns a clean error Response instead of a 500.
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

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator,
    HSAdministratorPosition,
    HSPosition,
)
from cis.models.term import AcademicYear, Term

User = get_user_model()

ADD_TEACHER_URL = (
    '/highschool_admin/future_sections/api/actions/add-teacher/'
)


class AddTeacherBoolCrashTests(TestCase):
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
        # HS admin role group. NOTE: we intentionally do NOT create the
        # 'instructor' group, so Teacher.get_or_add() will fail (return None)
        # for the brand-new teacher and AddNewTeacherForm.save() returns False.
        Group.objects.get_or_create(name='highschool_admin')

        cls.admin_user = User.objects.create_user(
            username='hsadmin_at', email='hsadmin_at@example.com',
            password='x', first_name='HS', last_name='Admin',
        )
        cls.admin_user.groups.add(Group.objects.get(name='highschool_admin'))

        cls.hs = HighSchool.objects.create(name='Crash HS')

        # HS admin must have an Active position at the school to pass the
        # role/permission checks for this endpoint.
        cls.hsadmin = HSAdministrator.objects.create(user=cls.admin_user)
        cls.position = HSPosition.objects.create(name='Principal')
        HSAdministratorPosition.objects.create(
            hsadmin=cls.hsadmin,
            highschool=cls.hs,
            position=cls.position,
            status='Active',
        )

        cls.cohort = Cohort.objects.create(name='CrashCo', designator='CRC')
        cls.course = Course.objects.create(
            name='CrashCourse', title='Crash', cohort=cls.cohort,
            catalog_number='101', credit_hours=3,
        )

        cls.academic_year = AcademicYear.objects.create(
            name='2026-2027',
            code='2627',
        )
        cls.term = Term.objects.create(
            academic_year=cls.academic_year,
            code='FA26',
            label='Fall 2026',
        )

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin_user)

    def _payload(self):
        return {
            'action': 'add_new_teacher',
            'academic_year_id': str(self.academic_year.id),
            'course_type': 'pathways',
            'highschool': str(self.hs.id),
            'term': str(self.term.id),
            'course': str(self.course.id),
            # "teacher not listed" branch: no 'teacher' value, new email.
            'teacher_not_listed': 'teacher_not_listed',
            'teacher_first_name': 'Brand',
            'teacher_last_name': 'New',
            'teacher_email': 'brand-new-teacher@example.com',
        }

    def test_add_teacher_failure_returns_clean_error_not_500(self):
        """When save() returns False, the endpoint must respond with a
        structured error (HTTP 400), never a 500/AttributeError."""
        resp = self.client.post(
            ADD_TEACHER_URL, data=self._payload(),
        )
        # Before the fix this is a 500 (AttributeError). After the fix it is a
        # clean 400 error Response.
        self.assertEqual(
            resp.status_code, 400,
            msg=f"Expected 400, got {resp.status_code}: {resp.content!r}",
        )
        body = resp.json()
        self.assertEqual(body.get('status'), 'error')
        self.assertIn('message', body)
