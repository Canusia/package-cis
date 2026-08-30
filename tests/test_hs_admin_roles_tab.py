import uuid

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
)


def _disconnect_login_signal():
    """django_login_history's post_login receiver crashes on the test client's
    missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class HsAdminRoleFixtureMixin:
    """Builds two admins, two schools and three roles.

    admin_a: Central/Principal (Active), North/Counselor (Active)
    admin_b: Central/Counselor (Inactive)
    """

    def build_fixture(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        Group.objects.get_or_create(name='highschool_admin')
        self.staff = CustomUser.objects.create_superuser(
            username='hsrolestaff', email='hsrolestaff@example.com', password='x')
        self.staff.groups.add(ce_group)
        self.client.force_login(self.staff)

        self.central = HighSchool.objects.create(name='Central High', code='CEN')
        self.north = HighSchool.objects.create(name='North High', code='NOR')
        self.principal = HSPosition.objects.create(name='Principal')
        self.counselor = HSPosition.objects.create(name='Counselor')

        self.user_a = CustomUser.objects.create_user(
            username='admin_a', email='admin_a@example.com', password='x',
            first_name='Ann', last_name='Alpha')
        self.user_b = CustomUser.objects.create_user(
            username='admin_b', email='admin_b@example.com', password='x',
            first_name='Bob', last_name='Beta')
        self.admin_a = HSAdministrator.objects.create(user=self.user_a)
        self.admin_b = HSAdministrator.objects.create(user=self.user_b)

        self.role_a1 = HSAdministratorPosition.objects.create(
            hsadmin=self.admin_a, highschool=self.central,
            position=self.principal, status='Active')
        self.role_a2 = HSAdministratorPosition.objects.create(
            hsadmin=self.admin_a, highschool=self.north,
            position=self.counselor, status='Active')
        self.role_b1 = HSAdministratorPosition.objects.create(
            hsadmin=self.admin_b, highschool=self.central,
            position=self.counselor, status='Inactive')

    def tear_down_fixture(self):
        _reconnect_login_signal(self._saved)


class HsAdministratorPositionFilterTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def _ids(self, response):
        return {row['id'] for row in response.json()['data']}

    def test_unfiltered_returns_every_role(self):
        resp = self.client.get('/ce/api/hs-administrator-position/?format=datatables')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['data']), 3)

    def test_hsadmin_filter_limits_to_that_admin(self):
        resp = self.client.get(
            '/ce/api/hs-administrator-position/?format=datatables'
            f'&hsadmin={self.admin_a.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self._ids(resp),
            {str(self.role_a1.id), str(self.role_a2.id)})

    def test_unknown_but_valid_uuid_returns_empty(self):
        resp = self.client.get(
            '/ce/api/hs-administrator-position/?format=datatables'
            f'&hsadmin={uuid.uuid4()}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data'], [])

    def test_malformed_hsadmin_returns_empty_not_500(self):
        resp = self.client.get(
            '/ce/api/hs-administrator-position/?format=datatables'
            '&hsadmin=PLACEHOLDER')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['data'], [])


class HighSchoolRolesTabTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_tab_renders_the_datatable_partial(self):
        resp = self.client.get(reverse('cis:hs_admin', args=[self.admin_a.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('records_roles', body)
        self.assertIn('hs_admins_table.js', body)
        self.assertIn('bulk_action.js', body)

    def test_table_is_scoped_to_this_administrator(self):
        resp = self.client.get(reverse('cis:hs_admin', args=[self.admin_a.id]))
        self.assertIn(f'hsadmin={self.admin_a.id}', resp.content.decode())

    def test_tab_exposes_edit_status_and_delete_only(self):
        resp = self.client.get(reverse('cis:hs_admin', args=[self.admin_a.id]))
        body = resp.content.decode()
        self.assertIn("slug: 'edit_status'", body)
        self.assertIn("slug: 'delete'", body)
        self.assertNotIn("slug: 'change_password'", body)

    def test_delete_button_is_wired_to_post(self):
        resp = self.client.get(reverse('cis:hs_admin', args=[self.admin_a.id]))
        body = resp.content.decode()
        delete_spec = body[body.index("slug: 'delete'"):]
        self.assertIn("method: 'POST'", delete_spec[:400])

    def test_add_new_role_button_survives_the_conversion(self):
        resp = self.client.get(reverse('cis:hs_admin', args=[self.admin_a.id]))
        self.assertIn('Add New', resp.content.decode())
