"""Locked Accounts page — the /ce/users/locked/ feed and its unlock action.

Three defect classes are pinned here:

1. Authorization. Unlocking restores sign-in to an account the brute-force
   guard shut off, so the endpoint has to stand on its own rather than lean on
   the page gate. A CE user without `manage_staff_accounts` must be refused at
   both the feed and the bulk action.

2. Guard order in do_locked_bulk_action. The unknown-action check runs before
   the POST-only check, deliberately, so an unknown action arriving over GET
   can never reach a mutation. Swapping the two would turn a 400 into a 405
   and move the mutation guard behind a check an attacker controls — the tests
   below assert the exact status of both branches.

3. data-name paths. Server-side DataTables ordering and per-column search
   resolve `columns[i][name]` as an ORM path; a header whose data-name is not
   a real field 500s the endpoint with FieldError. Every orderable column in
   myce_tenant_configs/services/locked_users_table.py is exercised here.
"""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

FEED = '/ce/api/locked-user/'

SEARCHABLE = ['last_name', 'first_name', 'email']
ORDERABLE = SEARCHABLE + ['failed_login_attempts', 'last_login']


def datatables_query(order_by=None, direction='asc', search='',
                     column_search=None):
    """Build a server-side DataTables request for the locked_users columns."""
    parts = ['format=datatables', 'draw=1', 'start=0', 'length=10']
    for i, name in enumerate(ORDERABLE):
        parts += [
            f'columns[{i}][data]={name}',
            f'columns[{i}][name]={name}',
            f'columns[{i}][orderable]=true',
            f'columns[{i}][searchable]={"true" if name in SEARCHABLE else "false"}',
            f'columns[{i}][search][value]='
            f'{column_search if column_search and name == order_by else ""}',
        ]
    if order_by is not None:
        parts += [
            f'order[0][column]={ORDERABLE.index(order_by)}',
            f'order[0][dir]={direction}',
        ]
    if search:
        parts.append(f'search[value]={search}')
    return FEED + '?' + '&'.join(parts)


class LockedAccountsTests(TestCase):
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
        for name in ('ce', 'highschool_admin', 'student'):
            Group.objects.get_or_create(name=name)

        def make(username, email, group, **kwargs):
            user = User.objects.create_user(
                username=username, email=email, password='x', **kwargs)
            user.groups.add(Group.objects.get(name=group))
            return user

        cls.manager = make(
            'lock_mgr', 'lock_mgr@example.com', 'ce',
            first_name='Mona', last_name='Manager', is_staff=True)
        cls.manager.campus = {'manage_staff_accounts': 'Yes'}
        cls.manager.save()

        # CE role but no manage_staff_accounts -> can_edit_users is False.
        cls.plain_ce = make(
            'lock_plain', 'lock_plain@example.com', 'ce',
            first_name='Percy', last_name='Plain', is_staff=True)

        # Two locked accounts, spanning two different roles.
        cls.locked_staff = make(
            'lock_staff', 'lock_staff@example.com', 'ce',
            first_name='Sid', last_name='Staff',
            account_locked=True, failed_login_attempts=3)
        cls.locked_student = make(
            'lock_stu', 'lock_stu@example.com', 'student',
            first_name='Stu', last_name='Student',
            account_locked=True, failed_login_attempts=5)

        cls.unlocked_student = make(
            'open_stu', 'open_stu@example.com', 'student',
            first_name='Ollie', last_name='Open')

        cls.hsadmin = make(
            'lock_hsa', 'lock_hsa@example.com', 'highschool_admin',
            first_name='Hank', last_name='Admin')

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')
        self.bulk_url = reverse('cis:locked_users_bulk_action')

    def get_rows(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, msg=f'{url} -> {resp.status_code}')
        return json.loads(resp.content)

    def assert_still_locked(self, *users):
        for user in users:
            user.refresh_from_db()
            self.assertTrue(
                user.account_locked,
                msg=f'{user.username} should still be locked')

    # -- feed -------------------------------------------------------------

    def test_lists_locked_accounts_across_roles(self):
        self.client.force_login(self.manager)
        payload = self.get_rows(datatables_query())

        emails = {row['email'] for row in payload['data']}
        self.assertEqual(
            emails, {self.locked_staff.email, self.locked_student.email})
        self.assertNotIn(self.unlocked_student.email, emails)
        self.assertEqual(payload['recordsTotal'], 2)

    def test_roles_serialized_per_row(self):
        self.client.force_login(self.manager)
        payload = self.get_rows(datatables_query())

        by_email = {row['email']: row['roles'] for row in payload['data']}
        self.assertEqual(by_email[self.locked_staff.email], ['ce'])
        self.assertEqual(by_email[self.locked_student.email], ['student'])

    def test_ce_without_manage_staff_accounts_sees_nothing(self):
        self.assertFalse(self.plain_ce.can_edit_users)

        self.client.force_login(self.plain_ce)
        payload = self.get_rows(datatables_query())

        self.assertEqual(payload['data'], [])
        self.assertEqual(payload['recordsTotal'], 0)

    def test_non_cis_role_forbidden_on_feed(self):
        self.client.force_login(self.hsadmin)
        resp = self.client.get(FEED + '?format=json')
        self.assertEqual(resp.status_code, 403)

    def test_every_column_orders(self):
        self.client.force_login(self.manager)
        for name in ORDERABLE:
            for direction in ('asc', 'desc'):
                payload = self.get_rows(datatables_query(name, direction))
                self.assertEqual(payload['recordsTotal'], 2)

    def test_every_searchable_column_searches(self):
        self.client.force_login(self.manager)
        for name in SEARCHABLE:
            payload = self.get_rows(
                datatables_query(order_by=name, column_search='Staff'))
            self.assertEqual(payload['draw'], 1)

    # -- unlock bulk action -----------------------------------------------

    def test_unlock_clears_lock_and_counter(self):
        self.client.force_login(self.manager)
        resp = self.client.post(self.bulk_url, {
            'action': 'unlock',
            'ids[]': [self.locked_staff.id, self.locked_student.id],
        })

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertEqual(body['status'], 'success')
        self.assertIn('2 account(s) unlocked', body['message'])

        for user in (self.locked_staff, self.locked_student):
            user.refresh_from_db()
            self.assertFalse(user.account_locked)
            self.assertEqual(user.failed_login_attempts, 0)

    def test_get_with_valid_action_is_405_and_mutates_nothing(self):
        self.client.force_login(self.manager)
        resp = self.client.get(self.bulk_url, {
            'action': 'unlock',
            'ids[]': [self.locked_staff.id],
        })

        self.assertEqual(resp.status_code, 405)
        self.assert_still_locked(self.locked_staff)

    def test_unknown_action_over_post_is_400(self):
        self.client.force_login(self.manager)
        resp = self.client.post(self.bulk_url, {
            'action': 'delete_everything',
            'ids[]': [self.locked_staff.id],
        })

        self.assertEqual(resp.status_code, 400)
        self.assert_still_locked(self.locked_staff)

    def test_unknown_action_over_get_is_400_not_405(self):
        # Pins the guard ORDER: the unknown-action check runs first, so an
        # unknown action over GET is rejected as unknown before the method
        # check ever sees it. A swap here would be a silent regression.
        self.client.force_login(self.manager)
        resp = self.client.get(self.bulk_url, {'action': 'delete_everything'})

        self.assertEqual(resp.status_code, 400)

    def test_non_numeric_ids_are_skipped(self):
        self.client.force_login(self.manager)
        resp = self.client.post(self.bulk_url, {
            'action': 'unlock',
            'ids[]': ['abc', self.locked_staff.id],
        })

        self.assertEqual(resp.status_code, 200)
        self.locked_staff.refresh_from_db()
        self.assertFalse(self.locked_staff.account_locked)
        self.assert_still_locked(self.locked_student)

    def test_already_unlocked_id_reported_as_skipped(self):
        self.client.force_login(self.manager)
        resp = self.client.post(self.bulk_url, {
            'action': 'unlock',
            'ids[]': [self.unlocked_student.id],
        })

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertIn('0 account(s) unlocked', body['message'])
        self.assertIn('1 skipped', body['message'])

    def test_ce_without_manage_staff_accounts_cannot_unlock(self):
        self.client.force_login(self.plain_ce)
        resp = self.client.post(self.bulk_url, {
            'action': 'unlock',
            'ids[]': [self.locked_staff.id],
        })

        self.assertEqual(resp.status_code, 403)
        self.assert_still_locked(self.locked_staff)

    def test_non_cis_role_cannot_unlock(self):
        self.client.force_login(self.hsadmin)
        resp = self.client.post(self.bulk_url, {
            'action': 'unlock',
            'ids[]': [self.locked_staff.id],
        })

        self.assertNotEqual(resp.status_code, 200)
        self.assert_still_locked(self.locked_staff)

    # -- page -------------------------------------------------------------

    def test_page_gate(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('cis:locked_users')).status_code, 200)

        self.client.force_login(self.plain_ce)
        self.assertEqual(self.client.get(reverse('cis:locked_users')).status_code, 302)
