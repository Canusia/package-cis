"""PT-4: /ce/api/student must be object-scoped by role.

CE/faculty staff see all students; a highschool_admin sees only students in
the high schools they administer; an instructor sees only students in their
own class sections. Out-of-scope detail lookups return 404.
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

from cis.models.highschool import HighSchool
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear
from cis.models.section import ClassSection, StudentRegistration
from cis.models.highschool_administrator import (
    HSAdministrator, HSPosition, HSAdministratorPosition,
)

User = get_user_model()


def _ids(resp):
    payload = resp.json()
    rows = payload['data'] if isinstance(payload, dict) and 'data' in payload else (
        payload['results'] if isinstance(payload, dict) and 'results' in payload else payload)
    return {str(r['id']) for r in rows}


class StudentViewSetScopingTests(TestCase):
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
        for name in ('ce', 'faculty', 'highschool_admin', 'instructor', 'student'):
            Group.objects.get_or_create(name=name)
        # post_save on StudentRegistration falls back to the 'cron' user.
        User.objects.create_user(username='cron', email='cron@example.com', password='x')

        cls.hs_a = HighSchool.objects.create(name='HS Alpha')
        cls.hs_b = HighSchool.objects.create(name='HS Beta')

        def _student(uname, hs):
            u = User.objects.create_user(
                username=uname, email=f'{uname}@example.com', password='x',
                first_name=uname.title(), last_name='Test',
            )
            return Student.objects.create(user=u, highschool=hs)

        cls.stu_a_in_section = _student('stu_a1', cls.hs_a)   # HS Alpha, in instructor's section
        cls.stu_a_other     = _student('stu_a2', cls.hs_a)   # HS Alpha, NOT in instructor's section
        cls.stu_b           = _student('stu_b1', cls.hs_b)   # HS Beta

        # Instructor (Teacher) + a class section they teach, with stu_a1 registered.
        inst_user = User.objects.create_user(
            username='inst1', email='inst1@example.com', password='x',
            first_name='Ina', last_name='Structor',
        )
        inst_user.groups.add(Group.objects.get(name='instructor'))
        cls.instructor_user = inst_user
        teacher = Teacher.objects.create(user=inst_user)

        ay = AcademicYear.objects.create(name='2025-2026', code='2526')
        term = Term.objects.create(academic_year=ay, code='2530', label='Fall 2025')
        cohort = Cohort.objects.create(name='Cohort A', designator='CA')
        course = Course.objects.create(
            name='Algebra', title='Algebra I', cohort=cohort,
            catalog_number='101', credit_hours=3,
        )
        section = ClassSection.objects.create(
            course=course, term=term, teacher=teacher,
            class_number='1001', section_number='01',
        )
        StudentRegistration.objects.create(
            student=cls.stu_a_in_section, class_section=section,
            status='registered', status_changed_on={},
        )

        # CE admin.
        ce = User.objects.create_user(
            username='ce1', email='ce1@example.com', password='x', is_staff=True)
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        # Highschool admin for HS Alpha only.
        hsa_user = User.objects.create_user(
            username='hsa1', email='hsa1@example.com', password='x')
        hsa_user.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa_user
        hsadmin = HSAdministrator.objects.create(user=hsa_user)
        position = HSPosition.objects.create(name='Principal')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=cls.hs_a, position=position, status='Active')

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    # ---- list scoping ------------------------------------------------------
    def test_ce_sees_all_students(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get('/ce/api/student/?format=json')
        self.assertEqual(resp.status_code, 200)
        ids = _ids(resp)
        self.assertEqual(
            ids,
            {str(self.stu_a_in_section.id), str(self.stu_a_other.id), str(self.stu_b.id)})

    def test_highschool_admin_sees_only_their_school(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get('/ce/api/student/?format=json')
        self.assertEqual(resp.status_code, 200)
        ids = _ids(resp)
        self.assertEqual(ids, {str(self.stu_a_in_section.id), str(self.stu_a_other.id)})
        self.assertNotIn(str(self.stu_b.id), ids)

    def test_instructor_sees_only_their_section_students(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/student/?format=json')
        self.assertEqual(resp.status_code, 200)
        ids = _ids(resp)
        self.assertEqual(ids, {str(self.stu_a_in_section.id)})

    # ---- object-level retrieve (404 out of scope) --------------------------
    def test_instructor_cannot_retrieve_out_of_scope_student(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get(f'/ce/api/student/{self.stu_b.id}/?format=json')
        self.assertEqual(resp.status_code, 404)

    def test_highschool_admin_cannot_retrieve_out_of_scope_student(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(f'/ce/api/student/{self.stu_b.id}/?format=json')
        self.assertEqual(resp.status_code, 404)

    def test_ce_can_retrieve_any_student(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get(f'/ce/api/student/{self.stu_b.id}/?format=json')
        self.assertEqual(resp.status_code, 200)
