from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.student import Student
from cis.models.note import StudentNote
from cis.tests.test_student_role_revocation import StudentRoleFixtureMixin


class DanglingStudentFixtureMixin(StudentRoleFixtureMixin):
    """Adds two accounts in the student group with no Student record:

    dangling_plain: no other roles — deletable
    dangling_instructor: also an instructor — role revocable, account not
    deletable
    """

    def build_dangling(self):
        self.instructor_group, _ = Group.objects.get_or_create(name='instructor')

        # user_a and user_b are real students (Student records); they must
        # never appear in the dangling list.
        self.user_a.groups.add(self.student_group)
        self.user_b.groups.add(self.student_group)

        self.dangling_plain = CustomUser.objects.create_user(
            username='sdangle1', email='sdangle1@example.com', password='x',
            first_name='Sam', last_name='Stray')
        self.dangling_plain.groups.add(self.student_group)

        self.dangling_instructor = CustomUser.objects.create_user(
            username='sdangle2', email='sdangle2@example.com', password='x',
            first_name='Ida', last_name='Idle')
        self.dangling_instructor.groups.add(self.student_group)
        self.dangling_instructor.groups.add(self.instructor_group)


class DanglingStudentViewSetTests(DanglingStudentFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.build_dangling()

    def tearDown(self):
        self.tear_down_fixture()

    def _rows(self):
        resp = self.client.get('/ce/api/student-dangling/?format=datatables')
        self.assertEqual(resp.status_code, 200)
        return {str(row['id']): row for row in resp.json()['data']}

    def test_lists_only_accounts_with_no_student_record(self):
        rows = self._rows()
        self.assertEqual(
            set(rows.keys()),
            {str(self.dangling_plain.id), str(self.dangling_instructor.id)})

    def test_excludes_users_outside_the_group(self):
        outsider = CustomUser.objects.create_user(
            username='soutsider', email='soutsider@example.com', password='x')
        outsider.groups.add(self.instructor_group)
        self.assertNotIn(str(outsider.id), self._rows())

    def test_reports_other_roles(self):
        rows = self._rows()
        self.assertEqual(rows[str(self.dangling_plain.id)]['other_roles'], [])
        self.assertEqual(
            rows[str(self.dangling_instructor.id)]['other_roles'],
            ['instructor'])

    def test_ordering_by_last_name_does_not_500(self):
        resp = self.client.get(
            '/ce/api/student-dangling/?format=datatables'
            '&order[0][column]=0&order[0][dir]=asc'
            '&columns[0][data]=last_name&columns[0][name]=last_name'
            '&columns[0][orderable]=true&columns[0][searchable]=true')
        self.assertEqual(resp.status_code, 200)
        names = [row['last_name'] for row in resp.json()['data']]
        self.assertEqual(names, sorted(names))

    def test_an_account_leaves_the_list_once_it_has_a_record(self):
        Student.objects.create(user=self.dangling_plain)
        self.assertNotIn(str(self.dangling_plain.id), self._rows())


class DanglingStudentBulkActionTests(DanglingStudentFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.build_dangling()
        self.url = reverse('cis:student_do_dangling_bulk_action')

    def tearDown(self):
        self.tear_down_fixture()

    def test_revoke_access_drops_the_group_and_keeps_the_account(self):
        resp = self.client.post(self.url, {
            'action': 'revoke_access',
            'ids[]': [str(self.dangling_instructor.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.dangling_instructor.refresh_from_db()
        self.assertNotIn('student', self.dangling_instructor.get_roles())
        self.assertIn('instructor', self.dangling_instructor.get_roles())
        self.assertTrue(
            CustomUser.objects.filter(pk=self.dangling_instructor.pk).exists())

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
            'ids[]': [str(self.dangling_instructor.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            CustomUser.objects.filter(pk=self.dangling_instructor.pk).exists())
        self.assertIn('1 skipped', resp.json()['message'])

    def test_delete_account_skips_a_protected_user(self):
        """A user referenced by a PROTECT foreign key cannot be deleted; the
        count must say so rather than the failure being swallowed, and it
        must be reported as the ordinary "skipped" case (a PROTECT
        reference is expected and explainable) rather than folded into the
        "failed unexpectedly" bucket reserved for a genuine surprise."""
        note = StudentNote()
        note.student = self.student_a
        note.createdby = self.dangling_plain
        note.note = 'protects the author'
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
        """CustomUser's pk is an integer AutoField, not a UUID (which Student
        uses) — a non-numeric id (or a stray UUID from a different tab) must
        be silently discarded rather than raising."""
        resp = self.client.post(self.url, {
            'action': 'revoke_access',
            'ids[]': ['not-an-int', str(self.dangling_instructor.id)],
        })
        self.assertEqual(resp.status_code, 200)
        self.dangling_instructor.refresh_from_db()
        self.assertNotIn('student', self.dangling_instructor.get_roles())


class DanglingStudentCampusScopeTests(TestCase):
    """The dangling-student queryset is intentionally NOT campus-scoped.

    The campus signal used elsewhere for students
    (studentregistration__class_section__course__campus, see
    cis/campus_gate.py) is derived from a Student record's registrations. A
    dangling account has no Student record at all, so there is no campus
    signal to scope by — it is not a gap in the scoping, there is nothing to
    scope on. This pins that decision: a campus-limited ce user still sees
    every dangling account, exactly like an unverified student (no
    application yet) is already universally visible under
    scope_students_by_campus.
    """

    def setUp(self):
        self._saved_login_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []

        self.student_group, _ = Group.objects.get_or_create(name='student')
        ce_group, _ = Group.objects.get_or_create(name='ce')

        self.ce_user = CustomUser.objects.create_user(
            username='sdangle_ce', email='sdangle_ce@example.com', password='x')
        self.ce_user.groups.add(ce_group)
        self.ce_user.campus = {'process_campus': ['00000000-0000-0000-0000-000000000000']}
        self.ce_user.save()
        self.client.force_login(self.ce_user)

        self.dangling = CustomUser.objects.create_user(
            username='sdangle3', email='sdangle3@example.com', password='x',
            first_name='No', last_name='Campus')
        self.dangling.groups.add(self.student_group)

    def tearDown(self):
        user_logged_in.receivers = self._saved_login_receivers

    def test_campus_limited_ce_user_sees_dangling_accounts_from_any_campus(self):
        resp = self.client.get('/ce/api/student-dangling/?format=datatables')
        self.assertEqual(resp.status_code, 200)
        ids = {str(row['id']) for row in resp.json()['data']}
        self.assertIn(str(self.dangling.id), ids)


class DanglingTabTests(DanglingStudentFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.build_dangling()

    def tearDown(self):
        self.tear_down_fixture()

    def test_do_dangling_bulk_action_url_resolves(self):
        self.assertTrue(reverse('cis:student_do_dangling_bulk_action'))

    def test_students_index_renders_dangling_tab(self):
        resp = self.client.get(reverse('cis:students'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('href="#dangling"', body)
        self.assertIn('Dangling Accounts', body)
        self.assertIn('records_student_dangling', body)

    def test_students_index_does_not_shadow_the_shared_bulk_action_helper(self):
        """myce_tenant_configs/staticfiles/js/bulk_action.js assigns
        window.do_bulk_action for the Dangling Accounts tab's buttons. A
        page-level `function do_bulk_action(...)` declaration would be
        hoisted and silently shadow that global for every table on this
        page (this bit the instructors page — see
        cis/templates/cis/teachers/teachers.html's do_legacy_bulk_action)."""
        resp = self.client.get(reverse('cis:students'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn('function do_bulk_action(', body)
