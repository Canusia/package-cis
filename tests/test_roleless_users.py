"""No Role tab of /ce/users/ -- accounts with no group and no role record,
and its two-step bulk delete (package-cis #71).

Pinned here:

1. Who is listed. Roleless means no auth group AND no role record AND not a
   superuser. A record without its group is dangling, not roleless, and must
   stay off this tab -- it still belongs to someone.

2. Authorization. Deleting is permanent, so `can_edit_users` is enforced by
   the feed (empty queryset) and by the bulk endpoint (403) on its own.

3. Guard order matches do_locked_bulk_action: unknown action 400, then
   POST-only 405, then 403.

4. Re-check before delete. An account is re-resolved with roleless_users()
   when the ids arrive and re-checked with is_roleless() inside the delete
   transaction, so one that gained a role after the page or the preview
   loaded is skipped, never deleted. The requester is never a candidate.

5. Deletion goes through cis.services.user_deletion: authorship is
   reassigned to the requester and blockers are refused and reported.

6. The tenant seam is opt-in. A tenant without roleless_users_table.py keeps
   a working /ce/users/ (no tab) and gets system check cis.W005; these tests
   stub the module either way, so they hold on every tenant.
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from cis.models.course import CourseAdministrator
from cis.models.note import StudentNote
from cis.models.student import Student
from cis.services.role_access import (
    is_roleless, role_record_relations, roleless_users,
)

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

FEED = '/ce/api/user-roleless/'
SEARCHABLE = ['last_name', 'first_name', 'email']
ORDERABLE = SEARCHABLE + ['last_login', 'created_at']


def datatables_query(order_by=None, direction='asc', search=''):
    parts = ['format=datatables', 'draw=1', 'start=0', 'length=50']
    for i, name in enumerate(ORDERABLE):
        parts += [
            f'columns[{i}][data]={name}',
            f'columns[{i}][name]={name}',
            f'columns[{i}][orderable]=true',
            f'columns[{i}][searchable]={"true" if name in SEARCHABLE else "false"}',
            f'columns[{i}][search][value]=',
        ]
    if order_by is not None:
        parts += [f'order[0][column]={ORDERABLE.index(order_by)}',
                  f'order[0][dir]={direction}']
    if search:
        parts.append(f'search[value]={search}')
    return FEED + '?' + '&'.join(parts)


class _Base(TestCase):
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
        for name in ('ce', 'student'):
            Group.objects.get_or_create(name=name)

        def make(username, group=None, **kwargs):
            user = User.objects.create_user(
                username=username, email=f'{username}@example.com',
                password='x', **kwargs)
            if group:
                user.groups.add(Group.objects.get(name=group))
            return user

        cls.manager = make('nr_mgr', 'ce', first_name='Mona', last_name='Manager')
        cls.manager.campus = {'manage_staff_accounts': 'Yes'}
        cls.manager.save()
        # CE role but no manage_staff_accounts -> can_edit_users is False.
        cls.plain_ce = make('nr_plain', 'ce', first_name='Percy', last_name='Plain')

        # The only shape the tab lists: no group, no record.
        cls.roleless = make('nr_none', first_name='Nora', last_name='Nobody')
        cls.roleless_b = make('nr_none_b', first_name='Ned', last_name='Nobody')

        # Has a group.
        cls.grouped = make('nr_grouped', 'student')
        # Has a role record but lost its group: dangling, not roleless.
        cls.record_only = make('nr_record')
        Student.objects.create(user=cls.record_only)
        cls.record_only.groups.clear()
        # Superusers need no group.
        cls.superuser = User.objects.create_superuser(
            username='nr_super', email='nr_super@example.com', password='x')

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')

    def exists(self, user):
        return User.objects.filter(pk=user.pk).exists()


class RolelessServiceTests(_Base):
    def test_lists_only_accounts_with_no_group_and_no_record(self):
        ids = set(roleless_users().values_list('id', flat=True))
        self.assertIn(self.roleless.id, ids)
        self.assertIn(self.roleless_b.id, ids)
        for user in (self.grouped, self.record_only, self.superuser,
                     self.manager, self.plain_ce):
            self.assertNotIn(user.id, ids, msg=user.username)

    def test_is_roleless_rechecks_one_account(self):
        self.assertTrue(is_roleless(self.roleless))
        self.roleless.groups.add(Group.objects.get(name='student'))
        self.assertFalse(is_roleless(self.roleless))

    def test_role_records_count_but_an_api_token_does_not(self):
        labels = {rel.related_model._meta.label for rel in role_record_relations()}
        self.assertTrue({'cis.Student', 'cis.Teacher', 'cis.HSAdministrator'} <= labels)
        self.assertNotIn('authtoken.Token', labels)

        from rest_framework.authtoken.models import Token
        Token.objects.create(user=self.roleless)
        self.assertTrue(is_roleless(self.roleless))


class RolelessFeedTests(_Base):
    def rows(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, msg=f'{url} -> {resp.status_code}')
        return json.loads(resp.content)

    def test_feed_lists_roleless_accounts(self):
        self.client.force_login(self.manager)
        payload = self.rows(datatables_query())
        self.assertEqual({row['id'] for row in payload['data']},
                         {self.roleless.id, self.roleless_b.id})
        self.assertIn('created_at', payload['data'][0])

    def test_every_column_orders_and_names_search(self):
        self.client.force_login(self.manager)
        for name in ORDERABLE:
            for direction in ('asc', 'desc'):
                self.assertEqual(
                    self.rows(datatables_query(name, direction))['recordsTotal'], 2)
        payload = self.rows(datatables_query('last_name', search='Nora'))
        self.assertEqual([row['id'] for row in payload['data']], [self.roleless.id])

    def test_ce_without_manage_staff_accounts_sees_nothing(self):
        self.assertFalse(self.plain_ce.can_edit_users)
        self.client.force_login(self.plain_ce)
        payload = self.rows(datatables_query())
        self.assertEqual(payload['data'], [])

    def test_non_cis_role_forbidden_on_feed(self):
        self.client.force_login(self.grouped)
        self.assertEqual(self.client.get(FEED + '?format=json').status_code, 403)


class RolelessBulkActionTests(_Base):
    def setUp(self):
        super().setUp()
        self.url = reverse('cis:roleless_users_bulk_action')

    def post(self, action, *users, raw_ids=None):
        ids = raw_ids if raw_ids is not None else [u.id for u in users]
        return self.client.post(self.url, {'action': action, 'ids[]': ids})

    def message(self, resp):
        body = json.loads(resp.content)
        self.assertEqual(body['outcome'], 'call')
        self.assertEqual(body['fn'], 'onBulkActionComplete')
        return body['args']['message']

    # -- guards ---------------------------------------------------------------

    def test_unknown_action_is_400_over_get_and_post(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self.url, {'action': 'nuke'}).status_code, 400)
        # The staff-account slugs are not accepted here.
        self.assertEqual(self.post('delete', self.roleless).status_code, 400)
        self.assertTrue(self.exists(self.roleless))

    def test_known_action_over_get_is_405_and_deletes_nothing(self):
        self.client.force_login(self.manager)
        resp = self.client.get(self.url, {'action': 'delete_account',
                                          'ids[]': [self.roleless.id]})
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(self.exists(self.roleless))

    def test_ce_without_manage_staff_accounts_is_403(self):
        self.client.force_login(self.plain_ce)
        self.assertEqual(self.post('preview_delete', self.roleless).status_code, 403)
        self.assertEqual(self.post('delete_account', self.roleless).status_code, 403)
        self.assertTrue(self.exists(self.roleless))

    # -- preview --------------------------------------------------------------

    def test_preview_is_read_only_and_shows_each_plan(self):
        StudentNote.objects.create(note='n', createdby=self.roleless,
                                   createdon=timezone.now())
        CourseAdministrator.objects.create(user=self.roleless_b)
        self.client.force_login(self.manager)

        resp = self.post('preview_delete', self.roleless, self.roleless_b, self.grouped)

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertEqual(body['outcome'], 'modal')
        html = body['html']
        self.assertIn('reassigned to you', html)
        self.assertIn('cis.CourseAdministrator.user', html)
        self.assertIn('1 selected row(s) skipped', html)
        self.assertIn('id="roleless_delete_confirm"', html)
        self.assertIn('name="action" value="delete_account"', html)
        # Only the deletable account is carried into the confirm form.
        self.assertIn(f'name="ids[]" value="{self.roleless.id}"', html)
        self.assertNotIn(f'name="ids[]" value="{self.roleless_b.id}"', html)
        self.assertTrue(self.exists(self.roleless))

    # -- delete ---------------------------------------------------------------

    def test_deletes_and_reassigns_authorship_to_the_requester(self):
        note = StudentNote.objects.create(note='n', createdby=self.roleless,
                                          createdon=timezone.now())
        self.client.force_login(self.manager)

        msg = self.message(self.post('delete_account', self.roleless))

        self.assertIn('1 account(s) deleted', msg)
        self.assertFalse(self.exists(self.roleless))
        note.refresh_from_db()
        self.assertEqual(note.createdby_id, self.manager.id)

    def test_never_deletes_an_account_with_a_role(self):
        self.client.force_login(self.manager)
        msg = self.message(self.post(
            'delete_account', self.grouped, self.record_only, self.superuser,
            self.manager))
        self.assertIn('0 account(s) deleted', msg)
        self.assertIn('4 skipped', msg)
        for user in (self.grouped, self.record_only, self.superuser, self.manager):
            self.assertTrue(self.exists(user), msg=user.username)

    def test_skips_an_account_that_gained_a_role_since_page_load(self):
        self.roleless.groups.add(Group.objects.get(name='student'))
        self.client.force_login(self.manager)
        msg = self.message(self.post('delete_account', self.roleless))
        self.assertIn('0 account(s) deleted', msg)
        self.assertTrue(self.exists(self.roleless))

    def test_rechecks_inside_the_delete_transaction(self):
        """A role granted after the ids were resolved -- between the preview
        and the confirm, or mid-batch -- is still caught."""
        self.client.force_login(self.manager)
        with mock.patch('cis.views.users.is_roleless', return_value=False) as recheck:
            msg = self.message(self.post('delete_account', self.roleless))
        recheck.assert_called_once()
        self.assertIn('0 account(s) deleted', msg)
        self.assertTrue(self.exists(self.roleless))

    def test_blocked_account_is_reported_and_kept(self):
        CourseAdministrator.objects.create(user=self.roleless_b)
        self.client.force_login(self.manager)
        msg = self.message(self.post('delete_account', self.roleless, self.roleless_b))
        self.assertIn('1 account(s) deleted', msg)
        self.assertIn('1 blocked', msg)
        self.assertFalse(self.exists(self.roleless))
        self.assertTrue(self.exists(self.roleless_b))

    def test_requesting_user_is_never_a_candidate(self):
        from cis.views.users import _selected_roleless

        request = RequestFactory().post(self.url)
        request.user = self.roleless
        users, skipped = _selected_roleless(
            request, [str(self.roleless.id), str(self.roleless_b.id)])
        self.assertEqual(users, [self.roleless_b])
        self.assertEqual(skipped, 1)

    def test_non_numeric_ids_are_skipped_not_500ed(self):
        self.client.force_login(self.manager)
        msg = self.message(self.post(
            'delete_account', raw_ids=['abc', '', str(self.roleless.id)]))
        self.assertIn('1 account(s) deleted', msg)
        self.assertIn('2 skipped', msg)


class UsersPageTabTests(_Base):
    """The tab rides on the tenant's roleless_users_table; stub it so these
    hold whether or not this tenant has adopted it."""

    def stub_module(self):
        calls = {}

        def build_config(**kwargs):
            calls.update(kwargs)
            return {'partial_template': 'cis/messages.html'}

        return SimpleNamespace(build_config=build_config), calls

    def get_page(self, get_table_config):
        self.client.force_login(self.manager)
        with mock.patch('cis.views.users.get_table_config', get_table_config):
            return self.client.get(reverse('cis:users'))

    def test_tab_rendered_and_wired_when_the_tenant_ships_the_config(self):
        module, calls = self.stub_module()
        resp = self.get_page(lambda name: module)

        self.assertEqual(resp.status_code, 200)
        page = resp.content.decode()
        self.assertIn('href="#no_role"', page)
        self.assertIn('id="no_role"', page)
        self.assertEqual(calls['variant'], 'roleless_users_index')
        self.assertEqual(calls['api_url'], '/ce/api/user-roleless?format=datatables')
        self.assertEqual(calls['bulk_actions_url'],
                         reverse('cis:roleless_users_bulk_action'))
        self.assertEqual(list(calls['bulk_actions']), ['preview_delete'])

    def test_page_renders_without_the_tab_when_the_config_is_missing(self):
        from django.conf import settings

        def missing(name):
            raise ModuleNotFoundError(
                'no roleless_users_table',
                name=f'{settings.TABLE_CONFIGS_APP}.services.{name}')

        resp = self.get_page(missing)
        self.assertEqual(resp.status_code, 200)
        page = resp.content.decode()
        self.assertNotIn('href="#no_role"', page)
        self.assertIn('id="users_filter"', page)

    def test_a_broken_tenant_module_is_not_mistaken_for_a_missing_one(self):
        def broken(name):
            raise ModuleNotFoundError('inner import failed', name='some_dependency')

        with self.assertRaises(ModuleNotFoundError):
            self.get_page(broken)

    @override_settings(TABLE_CONFIGS_APP='cis')
    def test_system_check_w005_when_the_module_is_missing(self):
        from cis.checks import roleless_users_table_check

        warnings = roleless_users_table_check(None)
        self.assertEqual([w.id for w in warnings], ['cis.W005'])
