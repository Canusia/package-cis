import uuid

from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition)
from cis.models.note import HSAdministratorNote
from cis.tests.test_hs_admin_roles_tab import HsAdminRoleFixtureMixin


class BulkEditStatusTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.url = reverse('cis:hs_admin_do_bulk_action')

    def tearDown(self):
        self.tear_down_fixture()

    def test_get_renders_the_modal_form(self):
        resp = self.client.get(self.url, {
            'action': 'edit_status',
            'ids[]': [str(self.role_a1.id), str(self.role_a2.id)],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('name="status"', body)
        self.assertIn('name="note"', body)
        self.assertIn('Central High', body)
        self.assertIn('frm_bulk_action', body)

    def test_post_sets_the_status_on_every_selected_role(self):
        resp = self.client.post(self.url, {
            'action': 'edit_status',
            'record_ids': [str(self.role_a1.id), str(self.role_b1.id)],
            'status': 'Inactive',
            'note': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['action'], 'reload_table')
        self.role_a1.refresh_from_db()
        self.role_a2.refresh_from_db()
        self.assertEqual(self.role_a1.status, 'Inactive')
        self.assertEqual(self.role_a2.status, 'Active')  # untouched

    def test_note_is_written_once_per_affected_admin(self):
        self.client.post(self.url, {
            'action': 'edit_status',
            'record_ids': [str(self.role_a1.id), str(self.role_a2.id),
                           str(self.role_b1.id)],
            'status': 'Inactive',
            'note': 'End of school year.',
        })
        notes = HSAdministratorNote.objects.all()
        self.assertEqual(notes.count(), 2)
        by_admin = {n.hsadmin_id: n for n in notes}
        self.assertIn(self.admin_a.id, by_admin)
        self.assertIn(self.admin_b.id, by_admin)
        note_a = by_admin[self.admin_a.id]
        self.assertIn('End of school year.', note_a.note)
        self.assertIn('Inactive', note_a.note)
        self.assertIn('Central High', note_a.note)
        self.assertIn('North High', note_a.note)
        self.assertEqual(note_a.createdby, self.staff)

    def test_no_note_is_written_when_the_box_is_empty(self):
        self.client.post(self.url, {
            'action': 'edit_status',
            'record_ids': [str(self.role_a1.id)],
            'status': 'Inactive',
            'note': '   ',
        })
        self.assertEqual(HSAdministratorNote.objects.count(), 0)

    def test_invalid_status_is_rejected(self):
        resp = self.client.post(self.url, {
            'action': 'edit_status',
            'record_ids': [str(self.role_a1.id)],
            'status': 'Banana',
            'note': '',
        })
        self.assertEqual(resp.status_code, 400)
        self.role_a1.refresh_from_db()
        self.assertEqual(self.role_a1.status, 'Active')

    def test_ids_outside_the_selection_are_ignored(self):
        """record_ids is client-supplied; only real position ids may be written."""
        resp = self.client.post(self.url, {
            'action': 'edit_status',
            'record_ids': [str(self.role_a1.id), 'not-a-uuid'],
            'status': 'Inactive',
            'note': '',
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            HSAdministratorPosition.objects.filter(status='Inactive').count(), 1)


class BulkDeleteRolesTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.url = reverse('cis:hs_admin_do_bulk_action')

    def tearDown(self):
        self.tear_down_fixture()

    def test_deletes_only_the_selected_roles(self):
        resp = self.client.post(self.url, {
            'action': 'delete',
            'ids[]': [str(self.role_a1.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'success')
        self.assertFalse(
            HSAdministratorPosition.objects.filter(id=self.role_a1.id).exists())
        self.assertTrue(
            HSAdministratorPosition.objects.filter(id=self.role_a2.id).exists())

    def test_the_administrator_survives_the_delete(self):
        self.client.post(self.url, {
            'action': 'delete',
            'ids[]': [str(self.role_a1.id), str(self.role_a2.id)],
        })
        self.admin_a.refresh_from_db()
        self.assertEqual(
            HSAdministratorPosition.objects.filter(hsadmin=self.admin_a).count(), 0)

    def test_get_is_refused(self):
        """Deletion must not be reachable by a GET."""
        resp = self.client.get(self.url, {
            'action': 'delete',
            'ids[]': [str(self.role_a1.id)],
        })
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(
            HSAdministratorPosition.objects.filter(id=self.role_a1.id).exists())

    def test_malformed_ids_are_skipped(self):
        resp = self.client.post(self.url, {
            'action': 'delete',
            'ids[]': ['not-a-uuid', str(self.role_a1.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            HSAdministratorPosition.objects.filter(id=self.role_a1.id).exists())

    def test_deletion_count_is_truthful(self):
        """Count reflects rows actually deleted, not well-formed-but-nonexistent IDs."""
        nonexistent_id = str(uuid.uuid4())
        resp = self.client.post(self.url, {
            'action': 'delete',
            'ids[]': [str(self.role_a1.id), nonexistent_id],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['message'], 'Successfully deleted 1 role(s).')


class BulkResetLinkTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.url = reverse('cis:hs_admin_do_bulk_action')

    def tearDown(self):
        self.tear_down_fixture()

    def test_lists_one_row_per_distinct_administrator(self):
        resp = self.client.get(self.url, {
            'action': 'password_reset_link',
            # Both of admin_a's roles are selected: the admin must appear once.
            'ids[]': [str(self.role_a1.id), str(self.role_a2.id),
                      str(self.role_b1.id)],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertEqual(body.count('admin_a@example.com'), 1)
        self.assertIn('admin_b@example.com', body)

    def test_each_row_carries_a_reset_link(self):
        resp = self.client.get(self.url, {
            'action': 'password_reset_link',
            'ids[]': [str(self.role_a1.id)],
        })
        body = resp.content.decode()
        # The real password_reset_confirm path is 'password_reset/<uidb64>/<token>'
        # (see myce/urls.py); '/reset/' does not appear anywhere in it.
        self.assertIn('/password_reset/', body)
        self.assertIn('Alpha', body)

    def test_malformed_ids_are_ignored(self):
        resp = self.client.get(self.url, {
            'action': 'password_reset_link',
            'ids[]': ['not-a-uuid'],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('admin_a@example.com', resp.content.decode())


class PersonBulkActionTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.url = reverse('cis:hs_admin_do_person_bulk_action')

    def tearDown(self):
        self.tear_down_fixture()

    def test_reset_links_take_administrator_ids_directly(self):
        resp = self.client.get(self.url, {
            'action': 'password_reset_link',
            'ids[]': [str(self.admin_a.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('admin_a@example.com', resp.content.decode())

    def test_delete_removes_the_record_and_keeps_the_account(self):
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_b).delete()
        resp = self.client.post(self.url, {
            'action': 'delete',
            'ids[]': [str(self.admin_b.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            HSAdministrator.objects.filter(id=self.admin_b.id).exists())
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())
        self.assertIn('1 administrator record(s) deleted', resp.json()['message'])

    def test_delete_revokes_the_role_when_no_roles_remain(self):
        from django.contrib.auth.models import Group
        hs_group, _ = Group.objects.get_or_create(name='highschool_admin')
        self.user_b.groups.add(hs_group)
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_b).delete()

        self.client.post(self.url, {
            'action': 'delete',
            'ids[]': [str(self.admin_b.id)],
        })
        self.user_b.refresh_from_db()
        self.assertNotIn('highschool_admin', self.user_b.get_roles())

    def test_delete_leaves_an_administrator_that_still_holds_roles(self):
        """admin_a's two roles reference the record with PROTECT: report it as
        left in place rather than cascading their roles away."""
        resp = self.client.post(self.url, {
            'action': 'delete',
            'ids[]': [str(self.admin_a.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            HSAdministrator.objects.filter(id=self.admin_a.id).exists())
        self.assertIn('1 account(s) left in place', resp.json()['message'])

    def test_delete_does_not_destroy_notes_when_the_record_survives(self):
        """delete_record raising ProtectedError must roll back the note
        deletion too, or the surviving admin loses their notes silently."""
        note = HSAdministratorNote.objects.create(
            hsadmin=self.admin_a, note='keep me', createdby=self.staff)

        resp = self.client.post(self.url, {
            'action': 'delete',
            'ids[]': [str(self.admin_a.id)],
        })

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            HSAdministrator.objects.filter(id=self.admin_a.id).exists())
        self.assertTrue(
            HSAdministratorNote.objects.filter(pk=note.pk).exists())
        self.assertIn('1 account(s) left in place', resp.json()['message'])

    def test_delete_is_refused_over_get(self):
        HSAdministratorPosition.objects.filter(hsadmin=self.admin_b).delete()
        resp = self.client.get(self.url, {
            'action': 'delete',
            'ids[]': [str(self.admin_b.id)],
        })
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(
            HSAdministrator.objects.filter(id=self.admin_b.id).exists())

    def test_change_password_renders_the_existing_modal(self):
        resp = self.client.get(self.url, {
            'action': 'change_password',
            'ids[]': [str(self.admin_a.id)],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('name="new_password"', body)
        self.assertIn('Alpha', body)

    def test_unknown_action_is_a_400(self):
        resp = self.client.get(self.url, {'action': 'nope', 'ids[]': []})
        self.assertEqual(resp.status_code, 400)
