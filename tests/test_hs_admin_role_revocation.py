from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition,
)
from cis.models.note import HSAdministratorNote
from cis.services.hs_admin_role import (
    has_remaining_hs_admin_records, revoke_hs_admin_access,
)
from cis.tests.test_hs_admin_roles_tab import HsAdminRoleFixtureMixin


class HsAdminRoleServiceTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.hs_group, _ = Group.objects.get_or_create(name='highschool_admin')
        self.user_a.groups.add(self.hs_group)
        self.user_b.groups.add(self.hs_group)

    def tearDown(self):
        self.tear_down_fixture()

    def test_has_remaining_records_is_true_while_a_record_exists(self):
        self.assertTrue(has_remaining_hs_admin_records(self.user_a))

    def test_revoke_refuses_while_a_record_exists(self):
        self.assertFalse(revoke_hs_admin_access(self.user_a))
        self.user_a.refresh_from_db()
        self.assertIn('highschool_admin', self.user_a.get_roles())

    def test_revoke_drops_the_group_once_the_record_is_gone(self):
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_a).delete()
        HSAdministrator.objects.filter(id=self.admin_a.id).delete()

        self.assertTrue(revoke_hs_admin_access(self.user_a))
        self.user_a.refresh_from_db()
        self.assertNotIn('highschool_admin', self.user_a.get_roles())

    def test_revoke_never_deletes_the_account(self):
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_a).delete()
        HSAdministrator.objects.filter(id=self.admin_a.id).delete()

        revoke_hs_admin_access(self.user_a)
        self.assertTrue(CustomUser.objects.filter(pk=self.user_a.pk).exists())

    def test_revoke_leaves_other_roles_alone(self):
        student_group, _ = Group.objects.get_or_create(name='student')
        self.user_a.groups.add(student_group)
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_a).delete()
        HSAdministrator.objects.filter(id=self.admin_a.id).delete()

        revoke_hs_admin_access(self.user_a)
        self.user_a.refresh_from_db()
        self.assertIn('student', self.user_a.get_roles())

    def test_revoke_clears_a_leftover_record_shell(self):
        """A record with no roles left is itself removed by the revoke, so the
        user cannot come back as a dangling account."""
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_b).delete()
        self.assertTrue(revoke_hs_admin_access(self.user_b))
        self.assertFalse(
            HSAdministrator.objects.filter(id=self.admin_b.id).exists())


class DeleteRecordKeepsTheAccountTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_delete_record_removes_only_the_administrator_record(self):
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_b).delete()
        HSAdministrator.delete_record(self.admin_b)

        self.assertFalse(
            HSAdministrator.objects.filter(id=self.admin_b.id).exists())
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())

    def test_delete_record_does_not_swallow_a_real_failure(self):
        """The old implementation wrapped user.delete() in a bare except, which
        is how accounts were left dangling. Deleting a record that still has
        roles must raise, not silently half-succeed."""
        with self.assertRaises(Exception):
            HSAdministrator.delete_record(self.admin_a)
        self.assertTrue(
            HSAdministrator.objects.filter(id=self.admin_a.id).exists())


class RevokeRoleEndpointTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.hs_group, _ = Group.objects.get_or_create(name='highschool_admin')
        self.user_b.groups.add(self.hs_group)
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_b).delete()
        HSAdministrator.objects.filter(id=self.admin_b.id).delete()

    def tearDown(self):
        self.tear_down_fixture()

    def _url(self, user):
        return reverse('cis:revoke_hs_admin_role', args=[user.id])

    def test_post_revokes(self):
        resp = self.client.post(self._url(self.user_b))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'success')
        self.user_b.refresh_from_db()
        self.assertNotIn('highschool_admin', self.user_b.get_roles())

    def test_get_is_refused(self):
        resp = self.client.get(self._url(self.user_b))
        self.assertEqual(resp.status_code, 405)
        self.user_b.refresh_from_db()
        self.assertIn('highschool_admin', self.user_b.get_roles())

    def test_refuses_a_user_that_still_has_a_record(self):
        self.user_a.groups.add(self.hs_group)
        resp = self.client.post(self._url(self.user_a))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'error')
        self.user_a.refresh_from_db()
        self.assertIn('highschool_admin', self.user_a.get_roles())

    def test_message_names_retained_roles(self):
        student_group, _ = Group.objects.get_or_create(name='student')
        self.user_b.groups.add(student_group)
        resp = self.client.post(self._url(self.user_b))
        self.assertIn('student', resp.json()['message'])


class DeleteViewPayloadTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.hs_group, _ = Group.objects.get_or_create(name='highschool_admin')
        self.user_b.groups.add(self.hs_group)

    def tearDown(self):
        self.tear_down_fixture()

    def _delete(self, admin):
        return self.client.get(reverse('cis:delete_hs_admin', args=[admin.id]))

    def test_delete_offers_the_revoke_when_no_roles_remain(self):
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_b).delete()
        resp = self._delete(self.admin_b)
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(payload['hs_admin_role_revocable'])
        self.assertIn('Beta', payload['admin_name'])
        self.assertEqual(
            payload['revoke_url'],
            reverse('cis:revoke_hs_admin_role', args=[self.user_b.id]))

    def test_delete_does_not_offer_the_revoke_while_roles_remain(self):
        """admin_a keeps two roles, so the record delete fails and nothing is
        offered."""
        resp = self._delete(self.admin_a)
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(
            HSAdministrator.objects.filter(id=self.admin_a.id).exists())

    def test_other_roles_are_reported(self):
        student_group, _ = Group.objects.get_or_create(name='student')
        self.user_b.groups.add(student_group)
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_b).delete()
        payload = self._delete(self.admin_b).json()
        self.assertIn('student', payload['other_roles'])
        self.assertNotIn('highschool_admin', payload['other_roles'])

    def test_account_survives_the_delete(self):
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_b).delete()
        self._delete(self.admin_b)
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())


class DetailPageRevokeWiringTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_detail_page_loads_the_prompt_script(self):
        resp = self.client.get(reverse('cis:hs_admin', args=[self.admin_a.id]))
        body = resp.content.decode()
        self.assertIn('hs_admin_detail.js', body)
        self.assertIn('hs-admin-delete', body)
