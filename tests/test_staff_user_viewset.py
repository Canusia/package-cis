"""StaffUserViewSet — the /ce/users/ DataTable feed.

Two defect classes are pinned here:

1. Authorization. The page gates on `can_edit_users` (CIS role *plus*
   `manage_staff_accounts`), but a DRF permission class can only express the
   role half, so the second half lives on the queryset. A CE user without
   `manage_staff_accounts` must get an empty table, not the staff roster.

2. data-name paths. Server-side DataTables ordering and per-column search
   resolve `columns[i][name]` as an ORM path; a header whose data-name is not
   a real field 500s the endpoint with FieldError. Every orderable/searchable
   column in myce_tenant_configs/services/users_table.py is exercised below,
   so a header edit that breaks a path fails here instead of in the browser.
"""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from rest_framework.test import APIClient

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

ENDPOINT = '/ce/api/user/'

# Mirrors the users_index profile's orderable/searchable columns. Columns the
# service marks unsearchable (created_at, is_active, last_login) are ordered
# but never searched -- icontains against a datetime or boolean 500s.
SEARCHABLE = ['last_name', 'first_name', 'email', 'psid']
ORDERABLE = SEARCHABLE + ['created_at', 'is_active', 'last_login']


def datatables_query(order_by=None, direction='asc', search='',
                     column_search=None, extra=''):
    """Build a server-side DataTables request for the users_index columns."""
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
    if extra:
        parts.append(extra)
    return ENDPOINT + '?' + '&'.join(parts)


class StaffUserViewSetTests(TestCase):
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

        cls.staff_manager = make(
            'ce_manager', 'ce_manager@example.com', 'ce',
            first_name='Mona', last_name='Manager', is_staff=True)
        cls.staff_manager.campus = {'manage_staff_accounts': 'Yes'}
        cls.staff_manager.save()

        # CE role, but no manage_staff_accounts -> can_edit_users is False.
        cls.plain_ce = make(
            'ce_plain', 'ce_plain@example.com', 'ce',
            first_name='Percy', last_name='Plain', is_staff=True)

        cls.disabled_ce = make(
            'ce_disabled', 'ce_disabled@example.com', 'ce',
            first_name='Dana', last_name='Disabled', is_active=False)

        cls.hsadmin = make(
            'hsa_user', 'hsa_user@example.com', 'highschool_admin',
            first_name='Hank', last_name='Admin')
        cls.student = make(
            'stu_user', 'stu_user@example.com', 'student',
            first_name='Sam', last_name='Student')

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def get_rows(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, msg=f'{url} -> {resp.status_code}')
        return json.loads(resp.content)

    # -- authorization ----------------------------------------------------

    def test_staff_manager_sees_only_ce_group(self):
        self.client.force_login(self.staff_manager)
        payload = self.get_rows(datatables_query())

        emails = {row['email'] for row in payload['data']}
        self.assertIn(self.staff_manager.email, emails)
        self.assertIn(self.plain_ce.email, emails)
        self.assertIn(self.disabled_ce.email, emails)
        self.assertNotIn(self.hsadmin.email, emails)
        self.assertNotIn(self.student.email, emails)
        self.assertEqual(payload['recordsTotal'], 3)

    def test_ce_without_manage_staff_accounts_sees_nothing(self):
        self.assertFalse(self.plain_ce.can_edit_users)

        self.client.force_login(self.plain_ce)
        payload = self.get_rows(datatables_query())

        self.assertEqual(payload['data'], [])
        self.assertEqual(payload['recordsTotal'], 0)

    def test_non_cis_roles_forbidden(self):
        for user in (self.hsadmin, self.student):
            self.client.force_login(user)
            resp = self.client.get(ENDPOINT + '?format=json')
            self.assertEqual(
                resp.status_code, 403,
                msg=f'{user.username} should be 403, got {resp.status_code}')

    def test_anonymous_gets_no_data(self):
        # Session auth redirects anonymous callers to the login page rather
        # than returning 401/403; what matters is that no roster comes back.
        resp = self.client.get(ENDPOINT + '?format=json')
        self.assertIn(resp.status_code, (302, 401, 403))

    # -- data-name paths --------------------------------------------------

    def test_every_column_orders(self):
        self.client.force_login(self.staff_manager)
        for name in ORDERABLE:
            for direction in ('asc', 'desc'):
                payload = self.get_rows(datatables_query(name, direction))
                self.assertEqual(payload['recordsTotal'], 3)

    def test_every_searchable_column_searches(self):
        self.client.force_login(self.staff_manager)
        for name in SEARCHABLE:
            payload = self.get_rows(
                datatables_query(order_by=name, column_search='Manager'))
            self.assertEqual(payload['draw'], 1)

    def test_global_search_matches_one_row(self):
        self.client.force_login(self.staff_manager)
        payload = self.get_rows(datatables_query(search='ce_plain@example.com'))

        self.assertEqual(payload['recordsFiltered'], 1)
        self.assertEqual(payload['data'][0]['email'], self.plain_ce.email)

    # -- filter form ------------------------------------------------------

    def test_is_active_filter(self):
        self.client.force_login(self.staff_manager)

        active = self.get_rows(datatables_query(extra='is_active=true'))
        self.assertEqual(active['recordsTotal'], 2)
        self.assertNotIn(
            self.disabled_ce.email, {row['email'] for row in active['data']})

        inactive = self.get_rows(datatables_query(extra='is_active=false'))
        self.assertEqual(inactive['recordsTotal'], 1)
        self.assertEqual(inactive['data'][0]['email'], self.disabled_ce.email)

        # Anything else is ignored -- the "Any" option posts an empty value.
        for value in ('', 'yes', 'garbage'):
            unfiltered = self.get_rows(datatables_query(extra=f'is_active={value}'))
            self.assertEqual(unfiltered['recordsTotal'], 3)
