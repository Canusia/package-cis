"""Authorization tests for the student edit branch of add_new_ajax (PT-5).

POST/GET model=student to /ce/add_new_ajax/ dispatches to
cis.views.student.edit_record, which loads any Student by a client-supplied id
and saves StudentCISForm with no authorization check (IDOR -> any non-CE user
can tamper with any student's profile, including the account email).

These tests assert that only the 'ce' (CE administrator) role may reach the
handler: a highschool_admin (the role used in the exploit) and an anonymous
user receive 403 on both POST and GET and cannot mutate the student; a CE user
passes the gate (404 on a bogus student id, looked up via get_object_or_404).

The guard short-circuits BEFORE get_object_or_404, so the negative tests use a
bogus id: gate fired => 403; gate absent => 404.
"""
import uuid

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.student import Student

User = get_user_model()


class EditStudentAuthorizationTests(TestCase):
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
        for name in ('ce', 'highschool_admin', 'student'):
            Group.objects.get_or_create(name=name)

        cls.url = reverse('cis:add_new_ajax')
        cls.bogus_id = uuid.uuid4()

        # Target student whose profile/email must not be tampered with.
        student_user = User.objects.create_user(
            username='target_stud', email='orig@example.com',
            password='x', first_name='Original', last_name='Student',
        )
        cls.student = Student.objects.create(user=student_user)

        # CE administrator.
        ce = User.objects.create_user(
            username='ce_pt5', email='ce_pt5@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        # Highschool admin — the role used in the pentest exploit.
        hsa = User.objects.create_user(
            username='hsa_pt5', email='hsa_pt5@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def test_highschool_admin_post_is_403_and_no_mutation(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.post(self.url, {
            'model': 'student',
            'id': str(self.student.id),
            'first_name': 'Tampered',
            'email': 'attacker@example.com',
            'ajax': '1',
        })
        self.assertEqual(resp.status_code, 403)

        # The guard returns before form.save, so nothing was mutated.
        self.student.user.refresh_from_db()
        self.assertEqual(self.student.user.email, 'orig@example.com')
        self.assertEqual(self.student.user.first_name, 'Original')

    def test_highschool_admin_get_is_403(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(self.url, {
            'model': 'student',
            'id': str(self.student.id),
            'ajax': '1',
        })
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_post_is_not_admitted(self):
        # No login. In EWU, cis.middleware.LoginRequiredMiddleware gates the
        # add_new dispatcher (it has no login_required=False marker), so an
        # anonymous request is redirected to the login page (302) before the
        # method guard runs. Either way the anonymous caller is denied and the
        # student is never mutated. We assert it is NOT admitted (never 2xx)
        # and that nothing was saved.
        resp = self.client.post(self.url, {
            'model': 'student',
            'id': str(self.student.id),
            'email': 'attacker@example.com',
            'ajax': '1',
        })
        self.assertIn(resp.status_code, (302, 403))

        self.student.user.refresh_from_db()
        self.assertEqual(self.student.user.email, 'orig@example.com')

    def test_ce_is_admitted_to_student_edit(self):
        self.client.force_login(self.ce_user)
        resp = self.client.post(self.url, {
            'model': 'student',
            'id': str(self.bogus_id),
            'ajax': '1',
        })
        # Past the CE gate (not 403); 404 because the bogus student id is
        # looked up via get_object_or_404.
        self.assertNotEqual(resp.status_code, 403)
        self.assertEqual(resp.status_code, 404)
