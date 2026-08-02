"""Authorization tests for the teachernote add_new_ajax branch (PT-23).

POSTing model=teachernote to /ce/add_new_ajax/ must only succeed for the
'ce' (CE administrator) role. A highschool_admin (or any other non-CE role)
must receive 403 and create no TeacherNote record. The GET (form-prefill)
path for an instructor note must also be CE-only.
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

from cis.models.note import TeacherNote
from cis.models.teacher import Teacher

User = get_user_model()


class TeacherNoteAuthzTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for this test case.
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

        # Target instructor (teacher) whose note records are being protected.
        teacher_user = User.objects.create_user(
            username='target_teacher', email='target_teacher@example.com',
            password='x', first_name='Terry', last_name='Teacher',
        )
        cls.teacher = Teacher.objects.create(user=teacher_user)

        # CE administrator.
        ce = User.objects.create_user(
            username='ce_pt23', email='ce_pt23@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        # Highschool admin — the role used in the pentest exploit.
        hsa = User.objects.create_user(
            username='hsa_pt23', email='hsa_pt23@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

        # Instructor — the second role named in the directive. The fix already
        # blocks instructors because user_has_cis_role() is True only for 'ce';
        # this fixture lets us prove it explicitly.
        instr = User.objects.create_user(
            username='instr_pt23', email='instr_pt23@example.com', password='x',
            first_name='Ira', last_name='Instructor',
        )
        instr.groups.add(Group.objects.get(name='instructor'))
        cls.instructor_user = instr

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def _post_data(self):
        return {
            'model': 'teachernote',
            'id': '-1',
            'note': 'PT-23 authorization test note',
            'add_to': str(self.teacher.id),
            'reply_to': '',
            'ajax': '1',
        }

    def test_highschool_admin_cannot_create_teacher_note(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(
            TeacherNote.objects.filter(teacher=self.teacher).exists())

    def test_highschool_admin_cannot_open_teacher_note_form(self):
        # The GET branch renders the teacher add-note form; it must be CE-only.
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(
            self.url,
            {'model': 'teachernote', 'parent': str(self.teacher.id),
             'id': '-1', 'ajax': '1'})
        self.assertEqual(resp.status_code, 403)

    def test_instructor_cannot_create_teacher_note(self):
        # Directive: note creation must be disabled for the instructor role too.
        self.client.force_login(self.instructor_user)
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(
            TeacherNote.objects.filter(teacher=self.teacher).exists())

    def test_instructor_cannot_open_teacher_note_form(self):
        # The GET (form-prefill) branch must also be blocked for instructors.
        self.client.force_login(self.instructor_user)
        resp = self.client.get(
            self.url,
            {'model': 'teachernote', 'parent': str(self.teacher.id),
             'id': '-1', 'ajax': '1'})
        self.assertEqual(resp.status_code, 403)

    def test_ce_can_create_teacher_note(self):
        self.client.force_login(self.ce_user)
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')
        self.assertTrue(
            TeacherNote.objects.filter(
                teacher=self.teacher,
                note='PT-23 authorization test note').exists())
