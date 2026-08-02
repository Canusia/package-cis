"""Authorization tests for the teacherhighschool add_new dispatch branch (PT-8).

POSTing model=teacherhighschool to the add_new dispatcher must only succeed for
the 'ce' (CE administrator) role. A highschool_admin (or any other non-CE role)
must receive 403 and create no TeacherHighSchool record. Creating a
TeacherHighSchool also elevates the teacher's user into the 'instructor' group
(TeacherHighSchool.save), so this is a privilege-escalation gate.

The dispatcher is reachable from BOTH /ce/add_new_ajax/ (ungated at the URL in
ewu) and /highschool_admin/ajax/ (gated only to highschool_admin, then
delegating to the same dispatcher), so the per-branch guard is the sole defense.
This test drives /ce/add_new_ajax/ directly because that route applies no URL
guard, making it the strictest exercise of the in-handler check.
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

from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherHighSchool

User = get_user_model()


class TeacherHighSchoolAuthzTests(TestCase):
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
        # 'ce' = CE administrator role checked by user_has_cis_role.
        # 'instructor' is required because TeacherHighSchool.save() adds the
        # teacher's user to it via Group.objects.get(name='instructor').
        for name in ('ce', 'highschool_admin', 'instructor'):
            Group.objects.get_or_create(name=name)

        cls.url = reverse('cis:add_new_ajax')

        cls.hs = HighSchool.objects.create(name='HS Alpha')

        # Target teacher whose affiliation (and instructor elevation) is protected.
        teacher_user = User.objects.create_user(
            username='target_teacher', email='target_teacher@example.com',
            password='x', first_name='Terry', last_name='Teacher',
        )
        cls.teacher = Teacher.objects.create(user=teacher_user)

        # CE administrator.
        ce = User.objects.create_user(
            username='ce_pt8', email='ce_pt8@example.com', password='x',
            first_name='Cee', last_name='Ee', is_staff=True,
        )
        ce.groups.add(Group.objects.get(name='ce'))
        cls.ce_user = ce

        # Highschool admin — the role used in the pentest exploit.
        hsa = User.objects.create_user(
            username='hsa_pt8', email='hsa_pt8@example.com', password='x',
            first_name='Hank', last_name='Admin',
        )
        hsa.groups.add(Group.objects.get(name='highschool_admin'))
        cls.hsadmin_user = hsa

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')

    def _post_data(self):
        # Mirrors what add_new_highschool / TeacherHighSchoolForm read:
        # id='-1' (create), teacher (client-supplied UUID), highschool, status, ajax.
        return {
            'model': 'teacherhighschool',
            'id': '-1',
            'teacher': str(self.teacher.id),
            'highschool': str(self.hs.id),
            'status': 'In the Program',
            'ajax': '1',
        }

    def test_highschool_admin_cannot_create_teacherhighschool(self):
        self.client.force_login(self.hsadmin_user)
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(TeacherHighSchool.objects.count(), 0)

    def test_highschool_admin_cannot_open_teacherhighschool_form(self):
        # The GET branch prefills the add-affiliation form; it must be CE-only too.
        self.client.force_login(self.hsadmin_user)
        resp = self.client.get(
            self.url,
            {'model': 'teacherhighschool', 'parent': str(self.teacher.id),
             'id': '-1', 'ajax': '1'})
        self.assertEqual(resp.status_code, 403)

    def test_ce_can_create_teacherhighschool(self):
        self.client.force_login(self.ce_user)
        resp = self.client.post(self.url, self._post_data())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get('status'), 'success')
        self.assertEqual(
            TeacherHighSchool.objects.filter(
                teacher=self.teacher, highschool=self.hs).count(),
            1,
        )
