"""Term-filter UUID guard (PT-fuzz hardening).

A non-UUID `term` / `term_id` query parameter must NOT 500 the DataTables list
endpoints. Invalid, non-sentinel values return an empty result set (HTTP 200);
recognized sentinels keep their behavior; a real term UUID filters correctly.

Covers:
  - highschool_admin StudentViewSet      (/highschool_admin/api/students/)
  - highschool_admin RegistrationViewSet (/highschool_admin/api/registration/)
  - cis ClassSectionViewSet              (/ce/api/class_section/)
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

from django.conf import settings as django_settings

from cis.models.term import AcademicYear, Term
from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.settings import Setting
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
)

User = get_user_model()


def _rows(payload):
    """Normalize a DRF/datatables JSON payload into a list of row dicts."""
    if isinstance(payload, dict):
        if 'data' in payload:
            return payload['data']
        if 'results' in payload:
            return payload['results']
    return payload


class _SignalSilenceMixin:
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login handler raises in tests (no usable
        # request IP). Disconnect for the duration of the case.
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)


def _build_section_graph():
    """Create AcademicYear/Term/Cohort/Course and return (term, hs, section)."""
    academic_year = AcademicYear.objects.create(name='2025-2026')
    term = Term.objects.create(
        academic_year=academic_year, code='202630', label='Fall 2026',
    )
    cohort = Cohort.objects.create(name='Default Cohort', designator='DC')
    course = Course.objects.create(
        name='ENG101', title='English 101', catalog_number='101',
        cohort=cohort, credit_hours=3,
    )
    hs = HighSchool.objects.create(name='HS Alpha')
    section = ClassSection.objects.create(
        class_number='1001', section_number='A', term=term, course=course,
        highschool=hs,
    )
    return term, hs, course, section


class HSAdminStudentTermGuardTests(_SignalSilenceMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='highschool_admin')
        Group.objects.get_or_create(name='student')
        # post_save on StudentRegistration attributes a note to user 'cron'
        # when there is no current request.
        User.objects.create_user(username='cron', email='cron@example.com', password='x')

        cls.term, cls.hs, cls.course, cls.section = _build_section_graph()

        admin_user = User.objects.create_user(
            username='hsadmin', email='hsadmin@example.com', password='x',
            first_name='Hs', last_name='Admin',
        )
        admin_user.groups.add(Group.objects.get(name='highschool_admin'))
        cls.admin_user = admin_user
        hsadmin = HSAdministrator.objects.create(user=admin_user)
        position = HSPosition.objects.create(name='Counselor')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=cls.hs, position=position, status='Active',
        )

        stu_user = User.objects.create_user(
            username='stu1', email='stu1@example.com', password='x',
            first_name='Stu', last_name='One',
        )
        cls.student = Student.objects.create(user=stu_user, highschool=cls.hs)
        StudentRegistration.objects.create(
            student=cls.student, class_section=cls.section, status_changed_on={},
        )

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin_user)

    def _get(self, term):
        return self.client.get(f'/highschool_admin/api/students/?format=json&term={term}')

    def test_invalid_term_minus_two_returns_200_empty(self):
        resp = self._get('-2')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp.json()), [])

    def test_invalid_term_code_returns_200_empty(self):
        resp = self._get('202630')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp.json()), [])

    def test_invalid_term_alpha_returns_200_empty(self):
        resp = self._get('abc')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp.json()), [])

    def test_sentinel_minus_one_returns_all(self):
        resp = self._get('-1')
        self.assertEqual(resp.status_code, 200)
        ids = {str(r['id']) for r in _rows(resp.json())}
        self.assertIn(str(self.student.id), ids)

    def test_valid_term_uuid_filters_correctly(self):
        resp = self._get(str(self.term.id))
        self.assertEqual(resp.status_code, 200)
        ids = {str(r['id']) for r in _rows(resp.json())}
        self.assertEqual(ids, {str(self.student.id)})


class HSAdminRegistrationTermGuardTests(_SignalSilenceMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='highschool_admin')
        Group.objects.get_or_create(name='student')
        User.objects.create_user(username='cron', email='cron@example.com', password='x')

        cls.term, cls.hs, cls.course, cls.section = _build_section_graph()

        admin_user = User.objects.create_user(
            username='hsadmin', email='hsadmin@example.com', password='x',
            first_name='Hs', last_name='Admin',
        )
        admin_user.groups.add(Group.objects.get(name='highschool_admin'))
        cls.admin_user = admin_user
        hsadmin = HSAdministrator.objects.create(user=admin_user)
        position = HSPosition.objects.create(name='Counselor')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=cls.hs, position=position, status='Active',
        )

        stu_user = User.objects.create_user(
            username='stu1', email='stu1@example.com', password='x',
            first_name='Stu', last_name='One',
        )
        cls.student = Student.objects.create(user=stu_user, highschool=cls.hs)
        cls.registration = StudentRegistration.objects.create(
            student=cls.student, class_section=cls.section, status_changed_on={},
        )

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin_user)

    def _get(self, term):
        return self.client.get(f'/highschool_admin/api/registration/?format=json&term={term}')

    def test_invalid_term_minus_one_returns_200_empty(self):
        # '-1' is NOT a RegistrationViewSet sentinel (only '-2' is), so it is an
        # invalid term and must produce an empty result, not a 500.
        resp = self._get('-1')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp.json()), [])

    def test_invalid_term_minus_three_returns_200_empty(self):
        resp = self._get('-3')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp.json()), [])

    def test_invalid_term_code_returns_200_empty(self):
        resp = self._get('202630')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp.json()), [])

    def test_sentinel_minus_two_returns_all(self):
        # '-2' means "no term filter" -> all registrations in scope.
        resp = self._get('-2')
        self.assertEqual(resp.status_code, 200)
        ids = {str(r['id']) for r in _rows(resp.json())}
        self.assertIn(str(self.registration.id), ids)

    def test_valid_term_uuid_filters_correctly(self):
        resp = self._get(str(self.term.id))
        self.assertEqual(resp.status_code, 200)
        ids = {str(r['id']) for r in _rows(resp.json())}
        self.assertEqual(ids, {str(self.registration.id)})


class CisClassSectionTermGuardTests(_SignalSilenceMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='instructor')

        cls.term, cls.hs, cls.course, cls.section = _build_section_graph()

        # registration_terms() (cis.utils) reads a per-campus Setting; without it
        # the 'registration_terms' branch filters term__in=None and TypeErrors.
        Setting.objects.get_or_create(
            key=f'{django_settings.CAMPUS_CODE_PREFIX}_cis_registrations',
            defaults={'value': {'registration_terms': [str(cls.term.id)]}},
        )

        cls.staff = User.objects.create_user(
            username='staff_cs', email='staff_cs@example.com', password='x',
            first_name='S', last_name='T', is_staff=True,
        )
        cls.staff.groups.add(Group.objects.get(name='ce'))

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.staff)

    def _get(self, term):
        return self.client.get(f'/ce/api/class_section/?format=json&term={term}')

    def test_invalid_term_code_returns_200_empty(self):
        resp = self._get('202630')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp.json()), [])

    def test_invalid_term_alpha_returns_200_empty(self):
        resp = self._get('abc')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rows(resp.json()), [])

    def test_sentinel_minus_one_returns_all(self):
        resp = self._get('-1')
        self.assertEqual(resp.status_code, 200)
        ids = {str(r['id']) for r in _rows(resp.json())}
        self.assertIn(str(self.section.id), ids)

    def test_sentinel_registration_terms_does_not_500(self):
        resp = self._get('registration_terms')
        self.assertEqual(resp.status_code, 200)

    def test_valid_term_uuid_filters_correctly(self):
        resp = self._get(str(self.term.id))
        self.assertEqual(resp.status_code, 200)
        ids = {str(r['id']) for r in _rows(resp.json())}
        self.assertEqual(ids, {str(self.section.id)})
