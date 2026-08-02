from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.customuser import CustomUser
from cis.models.course import Course, Campus, Cohort

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


class CourseBulkCampusActionTests(TestCase):
    """Covers the /ce/courses/ 'Add/Update Campus' bulk action end-to-end,
    mirroring the modal-then-confirm flow of the existing bulk actions."""

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
        ce = Group.objects.get_or_create(name='ce')[0]
        cls.admin = CustomUser.objects.create(
            username='ce@x.com', email='ce@x.com', is_active=True)
        cls.admin.set_password('pw')
        cls.admin.save()
        cls.admin.groups.add(ce)

        cls.cohort = Cohort.objects.create(name='Co', designator='CO')
        cls.campus = Campus.objects.create(name='Cheney', code='CHY')
        cls.c1 = Course.objects.create(
            name='C1', title='One', cohort=cls.cohort,
            catalog_number='101', credit_hours=3)
        cls.c2 = Course.objects.create(
            name='C2', title='Two', cohort=cls.cohort,
            catalog_number='102', credit_hours=3)
        cls.url = reverse('cis:course_bulk_actions')

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_action_registered_in_bulk_scope(self):
        from myce.component_registry.course import course_actions
        slugs = {slug for g in course_actions.for_scope('bulk').values()
                 for slug in g['actions']}
        self.assertIn('update_course_campus', slugs)

    def test_first_pass_returns_modal_with_campus_select(self):
        resp = self.client.post(self.url, {
            'action': 'update_course_campus',
            'ids[]': [str(self.c1.id), str(self.c2.id)],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['outcome'], 'modal')
        self.assertIn('name="campus"', body['html'])
        self.assertIn(str(self.campus.id), body['html'])

    def test_confirm_pass_updates_campus_on_selected_courses(self):
        resp = self.client.post(self.url, {
            'action': 'update_course_campus',
            'action_confirmed': '1',
            'record_ids': [str(self.c1.id), str(self.c2.id)],
            'campus': str(self.campus.id),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['outcome'], 'call')
        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual(self.c1.campus_id, self.campus.id)
        self.assertEqual(self.c2.campus_id, self.campus.id)

    def test_confirm_requires_campus(self):
        resp = self.client.post(self.url, {
            'action': 'update_course_campus',
            'action_confirmed': '1',
            'record_ids': [str(self.c1.id)],
        })
        self.assertEqual(resp.status_code, 400)
        self.c1.refresh_from_db()
        self.assertIsNone(self.c1.campus_id)
