"""Regression tests for PT-33.

The Future Sections ``remove-teaching-status`` action must not perform a
destructive state change on GET. It must be POST-only (CSRF-protected) and
return 405 for GET, so a cross-site GET navigation cannot delete offering data.

See docs/superpowers/plans/2026-06-06-pt33-remove-teaching-status-csrf.md
"""
import importlib.util

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

# future_sections is an editable submodule; import its live models via the
# same conditional the rest of the codebase uses.
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.models import FutureCourse, FutureProjection
else:  # pragma: no cover
    from future_sections.models import FutureCourse, FutureProjection

from cis.models.course import Cohort, Course, TeacherCourseCertificate
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator,
    HSAdministratorPosition,
    HSPosition,
)
from cis.models.teacher import Teacher, TeacherHighSchool
from cis.models.term import AcademicYear

User = get_user_model()

REMOVE_URL = '/highschool_admin/future_sections/api/actions/remove-teaching-status/'


class RemoveTeachingStatusCsrfTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for the test case.
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
        Group.objects.get_or_create(name='highschool_admin')
        Group.objects.get_or_create(name='instructor')

        cls.admin_user = User.objects.create_user(
            username='hsadmin_pt33', email='hsadmin_pt33@example.com',
            password='x', first_name='HS', last_name='Admin',
        )
        cls.admin_user.groups.add(Group.objects.get(name='highschool_admin'))

        cls.hs = HighSchool.objects.create(name='PT33 High')
        # HS admin linked to the high school (via an Active position) so
        # validate_certificate_access / get_user_context resolves the school.
        cls.hs_admin = HSAdministrator.objects.create(user=cls.admin_user)
        cls.position = HSPosition.objects.create(name='PT33 Position')
        HSAdministratorPosition.objects.create(
            hsadmin=cls.hs_admin, highschool=cls.hs,
            position=cls.position, status='Active',
        )

        teacher_user = User.objects.create_user(
            username='teach_pt33', email='teach_pt33@example.com',
            password='x', first_name='Tea', last_name='Cher',
        )
        cls.teacher = Teacher.objects.create(user=teacher_user)
        cls.ths = TeacherHighSchool.objects.create(
            teacher=cls.teacher, highschool=cls.hs, status='active',
        )
        cls.cohort = Cohort.objects.create(name='PT33 Cohort', designator='PT33')
        cls.course = Course.objects.create(
            name='PT33Course', title='PT33', catalog_number='133',
            credit_hours=3, cohort=cls.cohort,
        )
        cls.cert = TeacherCourseCertificate.objects.create(
            teacher_highschool=cls.ths, course=cls.course, status='active',
        )
        cls.year = AcademicYear.objects.create(name='2026-2027')

    def setUp(self):
        self.client.force_login(self.admin_user)

    def _make_future_course(self):
        fp = FutureProjection.objects.create(
            academic_year=self.year, highschool=self.hs,
        )
        fc = FutureCourse.objects.create(
            teacher_course=self.cert, academic_year=self.year,
            section_info={'teaching': 'yes', 'sections': []},
            meta={'fp': str(fp.id), 'history': []},
        )
        return fc

    def test_get_does_not_delete_and_returns_405(self):
        fc = self._make_future_course()
        resp = self.client.get(REMOVE_URL, {
            'course_certificate_id': str(self.cert.certificate_id),
            'academic_year_id': str(self.year.id),
        })
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(
            FutureCourse.objects.filter(pk=fc.pk).exists(),
            'GET must NOT delete the FutureCourse row (PT-33).',
        )

    def test_post_deletes(self):
        fc = self._make_future_course()
        resp = self.client.post(REMOVE_URL, {
            'course_certificate_id': str(self.cert.certificate_id),
            'academic_year_id': str(self.year.id),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            FutureCourse.objects.filter(pk=fc.pk).exists(),
            'A valid POST should remove the FutureCourse row.',
        )

    def test_session_post_without_csrf_token_is_rejected(self):
        """A session-authenticated POST with no CSRF token must be rejected,
        proving CsrfViewMiddleware / SessionAuthentication enforcement (PT-33)."""
        fc = self._make_future_course()
        csrf_client = APIClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin_user)
        resp = csrf_client.post(REMOVE_URL, {
            'course_certificate_id': str(self.cert.certificate_id),
            'academic_year_id': str(self.year.id),
        }, format='multipart')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(
            FutureCourse.objects.filter(pk=fc.pk).exists(),
            'A tokenless cross-site-style POST must not delete the row.',
        )
