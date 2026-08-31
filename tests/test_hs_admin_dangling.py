from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.highschool_administrator import HSAdministrator
from cis.models.note import HSAdministratorNote
from cis.tests.test_hs_admin_roles_tab import HsAdminRoleFixtureMixin


class DanglingAccountFixtureMixin(HsAdminRoleFixtureMixin):
    """Adds two accounts in the highschool_admin group with no record:

    dangling_plain: no other roles — deletable
    dangling_student: also a student — role revocable, account not deletable
    """

    def build_dangling(self):
        self.hs_group, _ = Group.objects.get_or_create(name='highschool_admin')
        self.student_group, _ = Group.objects.get_or_create(name='student')

        # admin_a and admin_b are real administrators; they must never appear.
        self.user_a.groups.add(self.hs_group)
        self.user_b.groups.add(self.hs_group)

        self.dangling_plain = CustomUser.objects.create_user(
            username='dangle1', email='dangle1@example.com', password='x',
            first_name='Dana', last_name='Dangle')
        self.dangling_plain.groups.add(self.hs_group)

        self.dangling_student = CustomUser.objects.create_user(
            username='dangle2', email='dangle2@example.com', password='x',
            first_name='Sam', last_name='Stray')
        self.dangling_student.groups.add(self.hs_group)
        self.dangling_student.groups.add(self.student_group)


class DanglingViewSetTests(DanglingAccountFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.build_dangling()

    def tearDown(self):
        self.tear_down_fixture()

    def _rows(self):
        resp = self.client.get('/ce/api/hs-administrator-dangling/?format=datatables')
        self.assertEqual(resp.status_code, 200)
        return {str(row['id']): row for row in resp.json()['data']}

    def test_lists_only_accounts_with_no_administrator_record(self):
        rows = self._rows()
        self.assertEqual(
            set(rows.keys()),
            {str(self.dangling_plain.id), str(self.dangling_student.id)})

    def test_excludes_users_outside_the_group(self):
        outsider = CustomUser.objects.create_user(
            username='outsider', email='outsider@example.com', password='x')
        outsider.groups.add(self.student_group)
        self.assertNotIn(str(outsider.id), self._rows())

    def test_reports_other_roles(self):
        rows = self._rows()
        self.assertEqual(rows[str(self.dangling_plain.id)]['other_roles'], [])
        self.assertEqual(
            rows[str(self.dangling_student.id)]['other_roles'], ['student'])

    def test_ordering_by_last_name_does_not_500(self):
        resp = self.client.get(
            '/ce/api/hs-administrator-dangling/?format=datatables'
            '&order[0][column]=0&order[0][dir]=asc'
            '&columns[0][data]=last_name&columns[0][name]=last_name'
            '&columns[0][orderable]=true&columns[0][searchable]=true')
        self.assertEqual(resp.status_code, 200)
        names = [row['last_name'] for row in resp.json()['data']]
        self.assertEqual(names, sorted(names))

    def test_an_account_leaves_the_list_once_it_has_a_record(self):
        HSAdministrator.objects.create(user=self.dangling_plain)
        self.assertNotIn(str(self.dangling_plain.id), self._rows())


class DanglingBulkActionTests(DanglingAccountFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.build_dangling()
        self.url = reverse('cis:hs_admin_do_dangling_bulk_action')

    def tearDown(self):
        self.tear_down_fixture()

    def test_revoke_access_drops_the_group_and_keeps_the_account(self):
        resp = self.client.post(self.url, {
            'action': 'revoke_access',
            'ids[]': [str(self.dangling_student.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.dangling_student.refresh_from_db()
        self.assertNotIn('highschool_admin', self.dangling_student.get_roles())
        self.assertIn('student', self.dangling_student.get_roles())
        self.assertTrue(
            CustomUser.objects.filter(pk=self.dangling_student.pk).exists())

    def test_revoke_access_requires_post(self):
        resp = self.client.get(self.url, {
            'action': 'revoke_access',
            'ids[]': [str(self.dangling_plain.id)],
        })
        self.assertEqual(resp.status_code, 405)

    def test_delete_account_removes_a_user_with_no_other_roles(self):
        resp = self.client.post(self.url, {
            'action': 'delete_account',
            'ids[]': [str(self.dangling_plain.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            CustomUser.objects.filter(pk=self.dangling_plain.pk).exists())
        self.assertIn('1 account(s) deleted', resp.json()['message'])

    def test_delete_account_skips_a_user_with_another_role(self):
        resp = self.client.post(self.url, {
            'action': 'delete_account',
            'ids[]': [str(self.dangling_student.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            CustomUser.objects.filter(pk=self.dangling_student.pk).exists())
        self.assertIn('1 skipped', resp.json()['message'])

    def test_delete_account_skips_a_protected_user(self):
        """A user referenced by a PROTECT foreign key cannot be deleted; the
        count must say so rather than the failure being swallowed."""
        note = HSAdministratorNote()
        note.hsadmin = self.admin_a
        note.createdby = self.dangling_plain
        note.note = 'protects the author'
        note.save()

        resp = self.client.post(self.url, {
            'action': 'delete_account',
            'ids[]': [str(self.dangling_plain.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            CustomUser.objects.filter(pk=self.dangling_plain.pk).exists())
        self.assertIn('1 skipped', resp.json()['message'])

    def test_delete_account_refuses_a_user_that_has_a_record(self):
        resp = self.client.post(self.url, {
            'action': 'delete_account',
            'ids[]': [str(self.user_a.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(CustomUser.objects.filter(pk=self.user_a.pk).exists())
        self.assertIn('1 skipped', resp.json()['message'])

    def test_unknown_action_is_a_400(self):
        resp = self.client.post(self.url, {'action': 'nope', 'ids[]': []})
        self.assertEqual(resp.status_code, 400)

    def test_non_numeric_id_is_skipped_not_500ed(self):
        """CustomUser's pk is an integer AutoField, not a UUID — a
        non-numeric id (or a stray UUID from a different tab) must be
        silently discarded rather than raising."""
        resp = self.client.post(self.url, {
            'action': 'revoke_access',
            'ids[]': ['not-an-int', str(self.dangling_student.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.dangling_student.refresh_from_db()
        self.assertNotIn('highschool_admin', self.dangling_student.get_roles())
