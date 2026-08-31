from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.teacher import Teacher
from cis.models.note import TeacherNote
from cis.tests.test_instructor_role_revocation import InstructorRoleFixtureMixin


class DanglingInstructorFixtureMixin(InstructorRoleFixtureMixin):
    """Adds two accounts in the instructor group with no Teacher record:

    dangling_plain: no other roles — deletable
    dangling_student: also a student — role revocable, account not deletable
    """

    def build_dangling(self):
        self.student_group, _ = Group.objects.get_or_create(name='student')

        # user_a and user_b are real instructors (Teacher records); they must
        # never appear in the dangling list.
        self.user_a.groups.add(self.instructor_group)
        self.user_b.groups.add(self.instructor_group)

        self.dangling_plain = CustomUser.objects.create_user(
            username='idangle1', email='idangle1@example.com', password='x',
            first_name='Ida', last_name='Idle')
        self.dangling_plain.groups.add(self.instructor_group)

        self.dangling_student = CustomUser.objects.create_user(
            username='idangle2', email='idangle2@example.com', password='x',
            first_name='Sal', last_name='Stray')
        self.dangling_student.groups.add(self.instructor_group)
        self.dangling_student.groups.add(self.student_group)


class DanglingInstructorViewSetTests(DanglingInstructorFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.build_dangling()

    def tearDown(self):
        self.tear_down_fixture()

    def _rows(self):
        resp = self.client.get('/ce/api/instructor-dangling/?format=datatables')
        self.assertEqual(resp.status_code, 200)
        return {str(row['id']): row for row in resp.json()['data']}

    def test_lists_only_accounts_with_no_teacher_record(self):
        rows = self._rows()
        self.assertEqual(
            set(rows.keys()),
            {str(self.dangling_plain.id), str(self.dangling_student.id)})

    def test_excludes_users_outside_the_group(self):
        outsider = CustomUser.objects.create_user(
            username='ioutsider', email='ioutsider@example.com', password='x')
        outsider.groups.add(self.student_group)
        self.assertNotIn(str(outsider.id), self._rows())

    def test_reports_other_roles(self):
        rows = self._rows()
        self.assertEqual(rows[str(self.dangling_plain.id)]['other_roles'], [])
        self.assertEqual(
            rows[str(self.dangling_student.id)]['other_roles'], ['student'])

    def test_ordering_by_last_name_does_not_500(self):
        resp = self.client.get(
            '/ce/api/instructor-dangling/?format=datatables'
            '&order[0][column]=0&order[0][dir]=asc'
            '&columns[0][data]=last_name&columns[0][name]=last_name'
            '&columns[0][orderable]=true&columns[0][searchable]=true')
        self.assertEqual(resp.status_code, 200)
        names = [row['last_name'] for row in resp.json()['data']]
        self.assertEqual(names, sorted(names))

    def test_an_account_leaves_the_list_once_it_has_a_record(self):
        Teacher.objects.create(user=self.dangling_plain, status='active')
        self.assertNotIn(str(self.dangling_plain.id), self._rows())


class DanglingInstructorBulkActionTests(DanglingInstructorFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.build_dangling()
        self.url = reverse('cis:instructor_do_dangling_bulk_action')

    def tearDown(self):
        self.tear_down_fixture()

    def test_revoke_access_drops_the_group_and_keeps_the_account(self):
        resp = self.client.post(self.url, {
            'action': 'revoke_access',
            'ids[]': [str(self.dangling_student.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.dangling_student.refresh_from_db()
        self.assertNotIn('instructor', self.dangling_student.get_roles())
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
        count must say so rather than the failure being swallowed, and it
        must be reported as the ordinary "skipped" case (a PROTECT
        reference is expected and explainable) rather than folded into the
        "failed unexpectedly" bucket reserved for a genuine surprise."""
        note = TeacherNote()
        note.teacher = self.teacher_a
        note.createdby = self.dangling_plain
        note.note = 'protects the author'
        # meta['type'] must be a string, not absent: TeacherNote's post_save
        # signal does `'to_instructor' in instance.meta.get('type')` with no
        # None guard on the .get() result (pre-existing cis behavior, not
        # part of this feature).
        note.meta = {'type': ''}
        note.save()

        resp = self.client.post(self.url, {
            'action': 'delete_account',
            'ids[]': [str(self.dangling_plain.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            CustomUser.objects.filter(pk=self.dangling_plain.pk).exists())
        message = resp.json()['message']
        self.assertIn('1 skipped', message)
        self.assertNotIn('failed unexpectedly', message)

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

    def test_unknown_action_over_get_is_a_400_not_a_405(self):
        """The unknown-action check must run before the POST-only check, so
        an unknown action arriving over GET cannot reach a mutation."""
        resp = self.client.get(self.url, {'action': 'nope', 'ids[]': []})
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
        self.assertNotIn('instructor', self.dangling_student.get_roles())
