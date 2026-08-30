from django.test import TestCase
from django.urls import reverse

from cis.models.highschool_administrator import HSAdministratorPosition
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
