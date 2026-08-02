"""Authorization tests for the studentcampusid add_new_ajax branch (PT-12).

POSTing model=studentcampusid to /ce/add_new_ajax/ must only succeed for the
'ce' (CE administrator) role. A highschool_admin (or any other role) must
receive 403 and create no StudentCampusID record.
"""
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.student import Student, StudentCampusID
from cis.models.course import Campus

User = get_user_model()


class StudentCampusIDAuthzTests(TestCase):
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
        for name in ('ce', 'highschool_admin', 'instructor', 'student'):
            Group.objects.get_or_create(name=name)

        cls.url = reverse('cis:add_new_ajax')

        # Target student + a campus to map them to.
        student_user = User.objects.create_user(
            username='target_stud', email='target_stud@example.com',
            password='x', first_name='Tina', last_name='Target',
        )
        cls.student = Student.objects.create(user=student_user)
        cls.campus = Campus.objects.create(name='Main Campus', code='MAIN')

        # CE administrator.
        ce = User.objects.create_user(
            username='ce_pt12', email='ce_pt12@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        # Highschool admin — the role used in the pentest exploit.
        hsa = User.objects.create_user(
            username='hsa_pt12', email='hsa_pt12@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def _post_data(self):
        return {
            'model': 'studentcampusid',
            'id': '-1',
            'student_id': str(self.student.id),
            'campus': str(self.campus.id),
            'username': 'test_create',
            'user_id': 'PT-12-TEST',
            'email': 'test@example.com',
            'ajax': '1',
        }

    def test_highschool_admin_cannot_create_campus_id(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(
            StudentCampusID.objects.filter(user_id='PT-12-TEST').exists())

    def test_highschool_admin_cannot_prefill_form(self):
        # The GET branch prefills from an arbitrary StudentCampusID pk; it must
        # also be CE-only. First create a record as data, then try to read it.
        record = StudentCampusID.objects.create(
            student=self.student, campus=self.campus, user_id='EXISTING')
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(
            self.url,
            {'model': 'studentcampusid', 'id': str(record.id), 'ajax': '1'})
        self.assertEqual(resp.status_code, 403)

    def test_ce_can_create_campus_id(self):
        self.client.force_login(self.ce_user)
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')
        self.assertTrue(
            StudentCampusID.objects.filter(
                student=self.student, user_id='PT-12-TEST').exists())
