"""Authorization tests for TeacherViewSet (PT-11 directive on teacher records).

The /ce/api/teacher endpoint returns instructor (Teacher) records. Per the
PT-11 directive, "the teacher should be able to see only theirs; high school
admin should only be able to see teachers from their high school":

  * instructor        -> only their own Teacher record
  * highschool_admin  -> only teachers in the high schools they administer
  * ce / faculty      -> all teachers (CE instructors index + faculty
                         "My Instructors" both consume this endpoint)
  * any other role    -> no access (403)

Because retrieve() resolves through get_queryset(), an out-of-scope teacher
UUID returns 404 (object-level IDOR closed).
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
from cis.models.teacher import Teacher, TeacherHighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSPosition, HSAdministratorPosition,
)

User = get_user_model()


class TeacherViewSetAuthzTests(TestCase):
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
        for name in ('ce', 'faculty', 'instructor', 'highschool_admin', 'student'):
            Group.objects.get_or_create(name=name)

        # Two high schools in different "tenants".
        cls.hs_a = HighSchool.objects.create(name='HS Alpha')
        cls.hs_b = HighSchool.objects.create(name='HS Beta')

        # Teacher 1 (the instructor we authenticate as) at HS Alpha.
        u1 = User.objects.create_user(
            username='inst1', email='inst1@example.com', password='x',
            first_name='Ina', last_name='One',
        )
        u1.groups.add(Group.objects.get(name='instructor'))
        cls.teacher1 = Teacher.objects.create(user=u1)
        TeacherHighSchool.objects.create(
            teacher=cls.teacher1, highschool=cls.hs_a, status='In the Program',
        )
        cls.instructor_user = u1

        # Teacher 2 at HS Alpha (same school as teacher1 / the HS admin scope).
        u2 = User.objects.create_user(
            username='inst2', email='inst2@example.com', password='x',
            first_name='Ivo', last_name='Two',
        )
        cls.teacher2 = Teacher.objects.create(user=u2)
        TeacherHighSchool.objects.create(
            teacher=cls.teacher2, highschool=cls.hs_a, status='In the Program',
        )

        # Teacher 3 at HS Beta (a DIFFERENT school — out of HS-Alpha-admin scope).
        u3 = User.objects.create_user(
            username='inst3', email='inst3@example.com', password='x',
            first_name='Ike', last_name='Three',
        )
        cls.teacher3 = Teacher.objects.create(user=u3)
        TeacherHighSchool.objects.create(
            teacher=cls.teacher3, highschool=cls.hs_b, status='In the Program',
        )

        # Highschool admin for HS Alpha only.
        hsa_user = User.objects.create_user(
            username='hsadmin_a', email='hsadmin_a@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa_user.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa_user
        hsadmin = HSAdministrator.objects.create(user=hsa_user)
        position = HSPosition.objects.create(name='Principal')
        HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=cls.hs_a, position=position,
            status='Active',
        )

        # CE administrator.
        ce_user = User.objects.create_user(
            username='ce1', email='ce1@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce_user.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce_user

        # Faculty coordinator (spans schools; keeps full access).
        fac_user = User.objects.create_user(
            username='fac1', email='fac1@example.com', password='x',
            first_name='Fay', last_name='Faculty',
        )
        fac_user.groups.add(Group.objects.get(name='faculty'))
        cls.faculty_user = fac_user

        # A role with no business here.
        stud_user = User.objects.create_user(
            username='stud1', email='stud1@example.com', password='x',
            first_name='Sam', last_name='Student',
        )
        stud_user.groups.add(Group.objects.get(name='student'))
        cls.student_user = stud_user

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    @staticmethod
    def _ids(resp):
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        return {str(r['id']) for r in rows}

    # --- instructor ---------------------------------------------------------
    def test_instructor_sees_only_their_own_record(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/teacher/?format=json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), {str(self.teacher1.id)})

    def test_instructor_cannot_retrieve_other_teacher(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get(f'/ce/api/teacher/{self.teacher2.id}/?format=json')
        self.assertEqual(resp.status_code, 404)

    # --- highschool_admin ---------------------------------------------------
    def test_hsadmin_sees_only_teachers_in_their_highschool(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get('/ce/api/teacher/?format=json')
        self.assertEqual(resp.status_code, 200)
        # teacher1 + teacher2 are at HS Alpha; teacher3 is at HS Beta.
        self.assertEqual(
            self._ids(resp), {str(self.teacher1.id), str(self.teacher2.id)})

    def test_hsadmin_cannot_retrieve_out_of_scope_teacher(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(f'/ce/api/teacher/{self.teacher3.id}/?format=json')
        self.assertEqual(resp.status_code, 404)

    # --- ce / faculty (full access) -----------------------------------------
    def test_ce_sees_all_teachers(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get('/ce/api/teacher/?format=json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self._ids(resp),
            {str(self.teacher1.id), str(self.teacher2.id), str(self.teacher3.id)},
        )

    def test_faculty_sees_all_teachers(self):
        self.client.force_login(self.faculty_user)
        resp = self.client.get('/ce/api/teacher/?format=json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self._ids(resp),
            {str(self.teacher1.id), str(self.teacher2.id), str(self.teacher3.id)},
        )

    # --- unauthorized role --------------------------------------------------
    def test_student_role_is_forbidden(self):
        self.client.force_login(self.student_user)
        resp = self.client.get('/ce/api/teacher/?format=json')
        self.assertEqual(resp.status_code, 403)
