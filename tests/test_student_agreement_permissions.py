"""Authorization tests for StudentAgreementViewSet (pentest finding PT-6).

The /ce/api/student_agreement/ endpoint must be callable ONLY by CE (CIS)
staff. It returns every StudentAgreement plus nested student PII (email/phone/
address via StudentSerializer -> CustomUserSerializer), so instructor/faculty
sessions must NOT be able to enumerate it.

  * instructor -> 403
  * faculty    -> 403
  * ce (CE admin) -> 200, sees the records
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
from cis.models.student import Student, StudentAgreement
from cis.models.term import AcademicYear, Term

User = get_user_model()


class StudentAgreementPermissionTests(TestCase):
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
        for name in ('ce', 'instructor', 'faculty', 'student'):
            Group.objects.get_or_create(name=name)

        # The signed-agreement subject (a Student) and the term it covers.
        subject_user = User.objects.create_user(
            username='subj1', email='subj1@example.com', password='x',
            first_name='Sue', last_name='Subject',
        )
        highschool = HighSchool.objects.create(name='HS Alpha', code='ALP')
        student = Student.objects.create(user=subject_user, highschool=highschool)

        year = AcademicYear.objects.create(name='2025-2026')
        term = Term.objects.create(
            academic_year=year, code='FA25', label='Fall 2025',
        )

        StudentAgreement.objects.create(
            student=student, term=term, student_signature='sig',
        )

        # The three callers we authenticate as.
        cls.instructor_user = User.objects.create_user(
            username='inst1', email='inst1@example.com', password='x',
            first_name='Ina', last_name='Instructor',
        )
        cls.instructor_user.groups.add(Group.objects.get(name='instructor'))

        cls.faculty_user = User.objects.create_user(
            username='fac1', email='fac1@example.com', password='x',
            first_name='Faye', last_name='Faculty',
        )
        cls.faculty_user.groups.add(Group.objects.get(name='faculty'))

        cls.ce_user = User.objects.create_user(
            username='ce1', email='ce1@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        cls.ce_user.groups.add(Group.objects.get(name='ce'))

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def test_instructor_is_forbidden(self):
        self.client.force_login(self.instructor_user)
        resp = self.client.get('/ce/api/student_agreement/?format=json')
        self.assertEqual(resp.status_code, 403)

    def test_faculty_is_forbidden(self):
        self.client.force_login(self.faculty_user)
        resp = self.client.get('/ce/api/student_agreement/?format=json')
        self.assertEqual(resp.status_code, 403)

    def test_ce_staff_allowed(self):
        self.client.force_login(self.ce_user)
        resp = self.client.get('/ce/api/student_agreement/?format=json')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
        self.assertEqual(len(rows), 1)
