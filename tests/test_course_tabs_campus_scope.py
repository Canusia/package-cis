"""Campus-gate tests for the Teacher App Requirements and By Course Administrator tabs.

Covers:
  - CourseAppRequirementViewSet get_queryset scoping
  - CourseAdministratorViewSet get_queryset scoping (ce scoped; faculty unscoped)
  - update_app_requirements bulk action gate on confirm pass
"""
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, RequestFactory
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Campus, Cohort, Course, CourseAppRequirement, CourseAdministrator
from cis.views.course import CourseAppRequirementViewSet
from cis.views.faculty import CourseAdministratorViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _make_ce_user(campus_a):
    """Create a 'ce' user scoped to campus_a."""
    user = User.objects.create_user(
        username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
    user.groups.add(Group.objects.get_or_create(name='ce')[0])
    user.campus = {'process_campus': [str(campus_a.id)]}
    user.save()
    return user


def _make_faculty_user():
    """Create a 'faculty' user (no campus constraint)."""
    user = User.objects.create_user(
        username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')
    user.groups.add(Group.objects.get_or_create(name='faculty')[0])
    user.save()
    return user


class CourseAppRequirementViewSetScopeTests(TestCase):
    """ce user sees only campus_a + null-campus requirements; campus_b excluded."""

    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        self.rf = RequestFactory()
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')

        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus_a)
        self.course_b = Course.objects.create(
            catalog_number='201', title='B', cohort=self.cohort, campus=self.campus_b)
        self.course_none = Course.objects.create(
            catalog_number='100', title='N', cohort=self.cohort, campus=None)

        self.req_a = CourseAppRequirement.objects.create(
            course=self.course_a, name='Req-A')
        self.req_b = CourseAppRequirement.objects.create(
            course=self.course_b, name='Req-B')
        self.req_none = CourseAppRequirement.objects.create(
            course=self.course_none, name='Req-None')

        self.user = _make_ce_user(self.campus_a)

    def _queryset(self):
        req = self.rf.get('/ce/api/course-app-requirement')
        req.user = self.user
        vs = CourseAppRequirementViewSet()
        vs.request = req
        vs.format_kwarg = None
        return vs.get_queryset()

    def test_own_campus_and_null_campus_included(self):
        qs = self._queryset()
        self.assertIn(self.req_a, qs)
        self.assertIn(self.req_none, qs)

    def test_other_campus_excluded(self):
        qs = self._queryset()
        self.assertNotIn(self.req_b, qs)


class CourseAdministratorViewSetScopeTests(TestCase):
    """ce user is campus-scoped; faculty user sees all rows."""

    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        self.rf = RequestFactory()
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')

        self.course_a = Course.objects.create(
            catalog_number='301', title='A', cohort=self.cohort, campus=self.campus_a)
        self.course_b = Course.objects.create(
            catalog_number='401', title='B', cohort=self.cohort, campus=self.campus_b)
        self.course_none = Course.objects.create(
            catalog_number='300', title='N', cohort=self.cohort, campus=None)

        # A user to attach as the administrator
        self.admin_user = User.objects.create_user(
            username=f'adm_{_sfx()}', email=f'adm_{_sfx()}@x.com', password='x')

        self.ca_a = CourseAdministrator.objects.create(
            course=self.course_a, user=self.admin_user, role='Administrator', status='Active')
        self.ca_b = CourseAdministrator.objects.create(
            course=self.course_b, user=self.admin_user, role='Administrator', status='Active')
        self.ca_none = CourseAdministrator.objects.create(
            course=self.course_none, user=self.admin_user, role='Administrator', status='Active')

        self.ce_user = _make_ce_user(self.campus_a)
        self.faculty_user = _make_faculty_user()

    def _queryset(self, user):
        req = self.rf.get('/ce/api/course_administrator')
        req.user = user
        vs = CourseAdministratorViewSet()
        vs.request = req
        vs.format_kwarg = None
        return vs.get_queryset()

    def test_ce_user_sees_own_and_null_campus(self):
        qs = self._queryset(self.ce_user)
        self.assertIn(self.ca_a, qs)
        self.assertIn(self.ca_none, qs)

    def test_ce_user_excludes_other_campus(self):
        qs = self._queryset(self.ce_user)
        self.assertNotIn(self.ca_b, qs)

    def test_faculty_user_not_campus_filtered(self):
        """faculty role bypasses campus scoping — sees all rows."""
        qs = self._queryset(self.faculty_user)
        self.assertIn(self.ca_a, qs)
        self.assertIn(self.ca_b, qs)
        self.assertIn(self.ca_none, qs)


class UpdateAppRequirementsBulkGateTests(TestCase):
    """confirm pass of update_app_requirements must skip out-of-scope records."""

    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        self.campus_a = Campus.objects.create(
            name=f'A-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')

        self.course_a = Course.objects.create(
            catalog_number='501', title='A', cohort=self.cohort, campus=self.campus_a)
        self.course_b = Course.objects.create(
            catalog_number='601', title='B', cohort=self.cohort, campus=self.campus_b)

        self.req_a = CourseAppRequirement.objects.create(
            course=self.course_a, name='Req-X', status='Active')
        self.req_b = CourseAppRequirement.objects.create(
            course=self.course_b, name='Req-X', status='Active')

        self.user = _make_ce_user(self.campus_a)
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.user)

    def test_confirmed_bulk_update_skips_out_of_scope_requirement(self):
        resp = self.client.post(reverse('cis:course_bulk_actions'), {
            'action': 'update_app_requirements',
            'action_confirmed': '1',
            'ids[]': [str(self.req_a.id), str(self.req_b.id)],
            'new_status': 'Inactive',
            'new_required': '1',
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        self.req_a.refresh_from_db()
        self.req_b.refresh_from_db()
        self.assertEqual(self.req_a.status, 'Inactive')   # in-scope: updated
        self.assertEqual(self.req_b.status, 'Active')     # out-of-scope: untouched
