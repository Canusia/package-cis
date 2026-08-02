"""PT-38: /highschool_admin/api/course-actions/remove-teaching-status/ must
enforce the Future Sections submission window on the SERVER.

When the window is closed, a direct authenticated POST must be rejected with
HTTP 403 and must NOT delete the FutureCourse offering row. When the window is
open, the same POST succeeds and removes the row.

The window is driven by the `cis_future_sections` Setting's starting_date /
ending_date (m/d/Y), the same source FutureCourse.is_window_open() reads.
"""
import datetime
import importlib.util

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.settings import Setting
from cis.models.term import AcademicYear
from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
)

# Resolve the SAME FutureCourse the handler uses (editable-submodule aware).
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.models import FutureCourse
else:
    from future_sections.models import FutureCourse

User = get_user_model()

REMOVE_URL = '/highschool_admin/api/course-actions/remove-teaching-status/'


def _set_window(open_now):
    """Create/replace the cis_future_sections Setting so is_window_open() is
    True (open_now=True) or False (open_now=False)."""
    today = datetime.date.today()
    if open_now:
        start = today - datetime.timedelta(days=1)
        end = today + datetime.timedelta(days=1)
    else:
        # Entire window in the past -> closed.
        start = today - datetime.timedelta(days=30)
        end = today - datetime.timedelta(days=10)
    Setting.objects.update_or_create(
        key='cis_future_sections',
        defaults={'value': {
            'starting_date': start.strftime('%m/%d/%Y'),
            'ending_date': end.strftime('%m/%d/%Y'),
        }},
    )


class RemoveTeachingStatusWindowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal raises in tests (no IP).
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
        # TeacherHighSchool.save() adds the teacher to the 'instructor' group.
        Group.objects.get_or_create(name='instructor')

        cls.hs = HighSchool.objects.create(name='HS Alpha')

        # highschool_admin bound to cls.hs via an Active position.
        admin_user = User.objects.create_user(
            username='hsadmin38', email='hsadmin38@example.com', password='x',
            first_name='HS', last_name='Admin',
        )
        admin_user.groups.add(Group.objects.get(name='highschool_admin'))
        cls.admin_user = admin_user
        hsadmin = HSAdministrator.objects.create(user=admin_user)
        position = HSPosition.objects.create(name='Counselor')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=cls.hs, position=position,
            status='Active',
        )

        # Teacher + course + certificate at cls.hs.
        teacher_user = User.objects.create_user(
            username='teacher38', email='teacher38@example.com', password='x',
            first_name='Tea', last_name='Cher',
        )
        teacher = Teacher.objects.create(user=teacher_user)
        teacher_hs = TeacherHighSchool.objects.create(
            teacher=teacher, highschool=cls.hs,
        )
        cohort = Cohort.objects.create(name='Default Cohort', designator='DC')
        course = Course.objects.create(
            name='ENG101', title='English 101', catalog_number='101',
            cohort=cohort, credit_hours=3,
        )
        cls.cert = TeacherCourseCertificate.objects.create(
            teacher_highschool=teacher_hs, course=course, status='Teaching',
        )

        cls.academic_year = AcademicYear.objects.create(name='2025-2026')

    def setUp(self):
        # Fresh FutureCourse offering row for every test (it may get deleted).
        self.future_course = FutureCourse.objects.create(
            teacher_course=self.cert,
            academic_year=self.academic_year,
            meta={'teaching': 'no'},
        )
        self.client = APIClient()
        # force_login establishes a real session so cis.middleware
        # LoginRequiredMiddleware sees an authenticated user (force_authenticate
        # alone only sets request.user on the DRF request, not the session, so
        # the middleware would 302-redirect to '/').
        self.client.force_login(self.admin_user)
        self.client.force_authenticate(user=self.admin_user)

    def _post_remove(self):
        return self.client.post(REMOVE_URL, {
            'course_certificate_id': str(self.cert.certificate_id),
            'academic_year_id': str(self.academic_year.id),
        })

    def test_window_closed_rejects_and_does_not_delete(self):
        _set_window(open_now=False)

        resp = self._post_remove()

        self.assertEqual(resp.status_code, 403)
        # The offering row MUST still exist.
        self.assertTrue(
            FutureCourse.objects.filter(pk=self.future_course.pk).exists(),
            'FutureCourse was deleted despite a closed submission window',
        )

    def test_window_open_allows_and_deletes(self):
        _set_window(open_now=True)

        resp = self._post_remove()

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            FutureCourse.objects.filter(pk=self.future_course.pk).exists(),
            'FutureCourse should have been deleted while the window was open',
        )
