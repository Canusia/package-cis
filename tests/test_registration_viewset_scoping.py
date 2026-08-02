"""PT-14 (revised): /ce/api/registration/ is restricted to CIS (ce), faculty,
and instructor users. An instructor sees only registrations for their own
class sections; CE/faculty see all; highschool_admin is denied (403).

Built end-to-end over the real endpoint with APIClient, mirroring
cis/tests/test_teacher_course_viewset_filters.py (session login, the cis
LoginRequiredMiddleware needs a real session; django_login_history's
post_login signal is disconnected because the test request has no usable IP).
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import College, Department, Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator,
    HSAdministratorPosition,
    HSPosition,
)
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

User = get_user_model()


def _unique(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


class RegistrationViewSetScopingTests(TestCase):
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
        # Groups checked by the permission classes / role helpers.
        for name in ('ce', 'faculty', 'instructor', 'highschool_admin', 'student'):
            Group.objects.get_or_create(name=name)

        # StudentRegistration's post_save signal calls Student.add_note(),
        # which falls back to the 'cron' CustomUser when no request user is
        # present (as in tests). Provision it so fixture creation succeeds.
        User.objects.get_or_create(
            username='cron',
            defaults={'email': 'cron@example.com'},
        )

        # --- shared course/term graph (term-agnostic; tests pass term=-3) ---
        academic_year = AcademicYear.objects.create(name=_unique('AY'))
        cls.term = Term.objects.create(
            academic_year=academic_year, code='F25', label=_unique('Fall'),
        )
        college = College.objects.create(name=_unique('College'))
        department = Department.objects.create(
            name=_unique('Dept'), college=college,
        )
        cohort = Cohort.objects.create(name=_unique('Cohort'), designator='CO')
        course = Course.objects.create(
            catalog_number='101', title='Intro', department=department,
            cohort=cohort, credit_hours=3,
        )

        # --- two high schools, each with a student ---
        cls.hs_a = HighSchool.objects.create(name=_unique('HS-A'))
        cls.hs_b = HighSchool.objects.create(name=_unique('HS-B'))

        student_a = cls._make_student(cls.hs_a, 'stud-a')
        student_b = cls._make_student(cls.hs_b, 'stud-b')

        # --- instructor (Teacher) + a section they teach ---
        inst_user = User.objects.create_user(
            username=_unique('inst'), email=f'{_unique("inst")}@example.com',
            password='x', first_name='Ina', last_name='Structor',
        )
        inst_user.groups.add(Group.objects.get(name='instructor'))
        cls.instructor_user = inst_user
        teacher = Teacher.objects.create(user=inst_user)

        # section_a is taught by the instructor; section_b is not (no teacher).
        section_a = ClassSection.objects.create(
            class_number=_unique('CN'), section_number='01',
            term=cls.term, course=course, highschool=cls.hs_a,
            teacher=teacher,
        )
        section_b = ClassSection.objects.create(
            class_number=_unique('CN'), section_number='02',
            term=cls.term, course=course, highschool=cls.hs_b,
        )

        # reg_a is in the instructor's section; reg_b is not.
        cls.reg_a = StudentRegistration.objects.create(
            student=student_a, class_section=section_a, status_changed_on={},
        )
        cls.reg_b = StudentRegistration.objects.create(
            student=student_b, class_section=section_b, status_changed_on={},
        )

        # --- caller users ---
        cls.ce_user = User.objects.create_user(
            username=_unique('ce'), email=f'{_unique("ce")}@example.com',
            password='x', first_name='C', last_name='E', is_staff=True,
        )
        cls.ce_user.groups.add(Group.objects.get(name='ce'))

        cls.faculty_user = User.objects.create_user(
            username=_unique('fac'), email=f'{_unique("fac")}@example.com',
            password='x', first_name='F', last_name='Aculty',
        )
        cls.faculty_user.groups.add(Group.objects.get(name='faculty'))

        cls.hsadmin_user = cls._make_hs_admin_user(cls.hs_a)

    @staticmethod
    def _make_student(highschool, tag):
        user = User.objects.create_user(
            username=_unique(tag), email=f'{_unique(tag)}@example.com',
            password='x', first_name=tag, last_name='S',
        )
        return Student.objects.create(user=user, highschool=highschool)

    @classmethod
    def _make_hs_admin_user(cls, highschool):
        """A user in the highschool_admin group, bound to `highschool` via an
        Active HSAdministratorPosition."""
        user = User.objects.create_user(
            username=_unique('hsadmin'),
            email=f'{_unique("hsadmin")}@example.com',
            password='x', first_name='H', last_name='A',
        )
        user.groups.add(Group.objects.get(name='highschool_admin'))
        hsadmin = HSAdministrator.objects.create(user=user)
        position = HSPosition.objects.create(name=_unique('Pos'))
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=highschool,
            position=position, status='Active',
        )
        return user

    def setUp(self):
        # REMOTE_ADDR keeps any IP-based middleware happy.
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def _registration_ids(self):
        # term=-3 -> get_queryset sets term=None, so the term filter does not
        # exclude the seeded registrations regardless of active term.
        resp = self.client.get('/ce/api/registration/?format=json&term=-3')
        self.assertEqual(resp.status_code, 200, resp.content)
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        return {str(r['id']) for r in rows}

    def test_ce_staff_see_all_registrations(self):
        self.client.force_login(self.ce_user)
        ids = self._registration_ids()
        self.assertIn(str(self.reg_a.id), ids)
        self.assertIn(str(self.reg_b.id), ids)

    def test_faculty_see_all_registrations(self):
        self.client.force_login(self.faculty_user)
        ids = self._registration_ids()
        self.assertIn(str(self.reg_a.id), ids)
        self.assertIn(str(self.reg_b.id), ids)

    def test_instructor_sees_only_their_section_registrations(self):
        self.client.force_login(self.instructor_user)
        ids = self._registration_ids()
        self.assertIn(str(self.reg_a.id), ids)
        self.assertNotIn(str(self.reg_b.id), ids)

    def test_instructor_cannot_retrieve_out_of_scope_registration(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get(
            f'/ce/api/registration/{self.reg_b.id}/?format=json&term=-3')
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_highschool_admin_is_forbidden(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get('/ce/api/registration/?format=json&term=-3')
        self.assertEqual(resp.status_code, 403, resp.content)


class RegistrationViewSetUUIDGuardTests(TestCase):
    """PT-fuzz: a non-UUID `student` / `class_section` / `term` query param must
    return HTTP 200 with an empty/safe result, NOT a 500 ValidationError.
    Mirrors the PT-1 / term-filter-guard idiom. Role scoping (PT-14) still
    applies: these tests use a CE caller (full scope) so a non-empty result is
    only suppressed by the malformed-param guard, not by role."""

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

    @classmethod
    def setUpTestData(cls):
        for name in ('ce', 'instructor', 'student'):
            Group.objects.get_or_create(name=name)
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'},
        )

        academic_year = AcademicYear.objects.create(name=_unique('AY'))
        cls.term = Term.objects.create(
            academic_year=academic_year, code='F25', label=_unique('Fall'),
        )
        college = College.objects.create(name=_unique('College'))
        department = Department.objects.create(
            name=_unique('Dept'), college=college,
        )
        cohort = Cohort.objects.create(name=_unique('Cohort'), designator='CO')
        course = Course.objects.create(
            catalog_number='101', title='Intro', department=department,
            cohort=cohort, credit_hours=3,
        )
        cls.hs = HighSchool.objects.create(name=_unique('HS'))

        student_user = User.objects.create_user(
            username=_unique('stud'), email=f'{_unique("stud")}@example.com',
            password='x', first_name='Stu', last_name='Dent',
        )
        cls.student = Student.objects.create(
            user=student_user, highschool=cls.hs,
        )
        cls.section = ClassSection.objects.create(
            class_number=_unique('CN'), section_number='01',
            term=cls.term, course=course, highschool=cls.hs,
        )
        cls.reg = StudentRegistration.objects.create(
            student=cls.student, class_section=cls.section,
            status_changed_on={},
        )

        cls.ce_user = User.objects.create_user(
            username=_unique('ce'), email=f'{_unique("ce")}@example.com',
            password='x', first_name='C', last_name='E', is_staff=True,
        )
        cls.ce_user.groups.add(Group.objects.get(name='ce'))

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.ce_user)

    def _get(self, query):
        return self.client.get(f'/ce/api/registration/?format=json&{query}')

    def _ids(self, resp):
        payload = resp.json()
        rows = (payload['results']
                if isinstance(payload, dict) and 'results' in payload
                else payload)
        return {str(r['id']) for r in rows}

    # --- the reported crash: student='1' (also exercises term='-3') ---
    def test_student_numeric_does_not_500(self):
        resp = self._get('term=-3&student=1')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._ids(resp), set())

    def test_student_nonuuid_string_does_not_500(self):
        resp = self._get('term=-3&student=abc')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._ids(resp), set())

    def test_class_section_nonuuid_does_not_500(self):
        resp = self._get('term=-3&class_section=1')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._ids(resp), set())

    def test_term_nonuuid_code_does_not_500(self):
        # non-sentinel, non-UUID term (a term *code*, not its id)
        resp = self._get('term=202630')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._ids(resp), set())

    def test_term_minus_three_sentinel_still_works(self):
        # -3 => no term filter; CE sees the seeded registration
        resp = self._get('term=-3')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn(str(self.reg.id), self._ids(resp))

    # --- valid student UUID still filters correctly ---
    def test_valid_student_uuid_filters(self):
        resp = self._get(f'term=-3&student={self.student.id}')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._ids(resp), {str(self.reg.id)})

    def test_valid_student_uuid_with_no_regs_returns_empty(self):
        other = Student.objects.create(
            user=User.objects.create_user(
                username=_unique('o'), email=f'{_unique("o")}@example.com',
                password='x', first_name='O', last_name='Ther',
            ),
            highschool=self.hs,
        )
        resp = self._get(f'term=-3&student={other.id}')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._ids(resp), set())
