"""PT-25: /ce/api/class_section/ stays reachable by all roles, but the queryset
applies role-based ownership:

  - CIS ('ce') staff are unrestricted (multi-tenant listing).
  - highschool_admin may only pass a highschool_id they administer (else 403).
  - instructor is scoped to the sections they teach.

EWU has no test factories, so fixtures are built with direct Model.objects.create()
following webapp/cis/tests/test_teacher_course_viewset_filters.py. Queryset-level
behaviour (including PermissionDenied) is driven via RequestFactory; the end-to-end
403 status is asserted via DRF APIClient.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, RequestFactory
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.term import AcademicYear, Term
from cis.models.highschool import HighSchool
from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
)

User = get_user_model()


def _suffix():
    return uuid.uuid4().hex[:8]


def _user_in_group(group_name):
    sfx = _suffix()
    user = User.objects.create_user(
        username=f'{group_name}_{sfx}',
        email=f'{group_name}_{sfx}@example.com',
        password='x', first_name='F', last_name='L',
    )
    group, _ = Group.objects.get_or_create(name=group_name)
    user.groups.add(group)
    return user


def _hs_admin_bound_to(*highschools):
    user = _user_in_group('highschool_admin')
    hsadmin = HSAdministrator.objects.create(user=user)
    position = HSPosition.objects.create(name=f'Pos-{_suffix()}')
    for hs in highschools:
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=hs, position=position, status='Active',
        )
    return user


class ClassSectionViewSetScopingTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # (request has no usable IP). Disconnect for the duration of this case.
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        self.ay = AcademicYear.objects.create(name=f'AY-{_suffix()}')
        self.term = Term.objects.create(
            academic_year=self.ay, code='FA', label=f'Fall-{_suffix()}',
        )
        self.cohort = Cohort.objects.create(name=f'Co-{_suffix()}', designator='CO')
        self.course = Course.objects.create(
            catalog_number='101', title='Intro', cohort=self.cohort,
        )
        self.hs_a = HighSchool.objects.create(name=f'HS-A-{_suffix()}')
        self.hs_b = HighSchool.objects.create(name=f'HS-B-{_suffix()}')
        self.section_a = ClassSection.objects.create(
            term=self.term, course=self.course, highschool=self.hs_a,
        )
        self.section_b = ClassSection.objects.create(
            term=self.term, course=self.course, highschool=self.hs_b,
        )

    def _qs(self, user, **params):
        from cis.views.section import ClassSectionViewSet
        vs = ClassSectionViewSet()
        req = RequestFactory().get('/', params)
        req.user = user
        vs.request = req
        return vs.get_queryset()

    def test_cis_user_can_query_any_highschool(self):
        ce_user = _user_in_group('ce')
        ids = [r.id for r in self._qs(
            ce_user, term=str(self.term.id), highschool_id=str(self.hs_b.id),
        )]
        self.assertIn(self.section_b.id, ids)
        self.assertNotIn(self.section_a.id, ids)

    def test_highschool_admin_own_highschool_allowed(self):
        user = _hs_admin_bound_to(self.hs_a)
        ids = [r.id for r in self._qs(
            user, term=str(self.term.id), highschool_id=str(self.hs_a.id),
        )]
        self.assertIn(self.section_a.id, ids)
        self.assertNotIn(self.section_b.id, ids)

    def test_highschool_admin_other_highschool_forbidden(self):
        user = _hs_admin_bound_to(self.hs_a)
        with self.assertRaises(PermissionDenied):
            self._qs(user, term=str(self.term.id), highschool_id=str(self.hs_b.id))

    def test_highschool_admin_other_highschool_returns_403(self):
        user = _hs_admin_bound_to(self.hs_a)
        client = APIClient(REMOTE_ADDR='127.0.0.1')
        client.force_login(user)
        resp = client.get(
            '/ce/api/class_section/?format=json'
            f'&term={self.term.id}&highschool_id={self.hs_b.id}'
        )
        self.assertEqual(resp.status_code, 403)

    def test_instructor_scoped_to_their_sections(self):
        instructor = _user_in_group('instructor')
        teacher = Teacher.objects.create(user=instructor)
        self.section_a.teacher = teacher
        self.section_a.save()

        other_section = ClassSection.objects.create(
            term=self.term, course=self.course, highschool=self.hs_a,
            teacher=Teacher.objects.create(user=_user_in_group('instructor')),
        )

        ids = [r.id for r in self._qs(
            instructor, term=str(self.term.id), highschool_id=str(self.hs_a.id),
        )]
        self.assertIn(self.section_a.id, ids)
        self.assertNotIn(other_section.id, ids)
