"""/ce/users/ bulk actions -- enable, disable, and the two-step delete.

Pinned here:

1. Authorization differs per action and is enforced by the endpoint itself:
   enable/disable need `can_edit_users`; both delete steps need superuser.

2. Guard order matches do_locked_bulk_action: unknown action is 400 before the
   POST-only 405.

3. Scope guards: only `ce` accounts, never the requester's own account, and a
   non-superuser can never enable/disable a superuser.

4. A disabled account has no usable session. The email login views check
   is_active themselves, but SAML (django-saml-sp) logs the user in without
   checking; what actually stops them is ModelBackend.get_user rejecting
   inactive users on the next request. That is pinned here so a backend swap
   cannot silently turn "disabled" into a no-op.
"""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from cis.models.note import StudentNote
from cis.models.teacher import Teacher

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()


class UsersBulkActionTests(TestCase):
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

        def make(username, group='ce', **kwargs):
            user = User.objects.create_user(
                username=username, email=f'{username}@example.com',
                password='x', **kwargs)
            user.groups.add(Group.objects.get(name=group))
            return user

        cls.superuser = make('bulk_super', is_superuser=True, is_staff=True,
                             first_name='Sue', last_name='Super')
        cls.manager = make('bulk_mgr', is_staff=True,
                           first_name='Mona', last_name='Manager')
        cls.manager.campus = {'manage_staff_accounts': 'Yes'}
        cls.manager.save()
        cls.plain_ce = make('bulk_plain', first_name='Percy', last_name='Plain')

        cls.staff_a = make('bulk_a', first_name='Amy', last_name='Alpha')
        cls.staff_b = make('bulk_b', first_name='Bob', last_name='Beta')
        cls.other_super = make('bulk_super2', is_superuser=True,
                               first_name='Sam', last_name='Super')
        cls.student = make('bulk_stu', group='student',
                           first_name='Stu', last_name='Dent')

        cls.teacher_staff = make('bulk_teach', first_name='Theo', last_name='Teach')
        Teacher.objects.create(user=cls.teacher_staff, orientation_note='')

    def setUp(self):
        self.client = APIClient(REMOTE_ADDR='127.0.0.1')
        self.url = reverse('cis:users_bulk_action')

    def post(self, action, *users, raw_ids=None):
        ids = raw_ids if raw_ids is not None else [u.id for u in users]
        return self.client.post(self.url, {'action': action, 'ids[]': ids})

    def message(self, resp):
        """ActionRegistry envelope: the summary rides in the
        onBulkActionComplete args, not at the top level."""
        body = json.loads(resp.content)
        self.assertEqual(body['outcome'], 'call')
        self.assertEqual(body['fn'], 'onBulkActionComplete')
        return body['args']['message']

    def active(self, user):
        user.refresh_from_db()
        return user.is_active

    # -- guard order ----------------------------------------------------------

    def test_unknown_action_is_400_over_get_and_post(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(self.url, {'action': 'nuke'}).status_code, 400)
        self.assertEqual(self.post('nuke', self.staff_a).status_code, 400)

    def test_known_action_over_get_is_405_and_mutates_nothing(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(self.url, {'action': 'disable', 'ids[]': [self.staff_a.id]})
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(self.active(self.staff_a))

    # -- enable / disable -----------------------------------------------------

    def test_manager_can_disable_and_enable(self):
        self.client.force_login(self.manager)

        resp = self.post('disable', self.staff_a, self.staff_b)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('2 account(s) disabled', self.message(resp))
        self.assertFalse(self.active(self.staff_a))
        self.assertFalse(self.active(self.staff_b))

        resp = self.post('enable', self.staff_a)
        self.assertIn('1 account(s) enabled', self.message(resp))
        self.assertTrue(self.active(self.staff_a))

    def test_disable_writes_history(self):
        self.client.force_login(self.manager)
        before = User.history.filter(id=self.staff_a.id).count()
        self.post('disable', self.staff_a)
        self.assertEqual(User.history.filter(id=self.staff_a.id).count(), before + 1)

    def test_already_in_state_is_skipped(self):
        self.client.force_login(self.manager)
        resp = self.post('enable', self.staff_a)
        body = self.message(resp)
        self.assertIn('0 account(s) enabled', body)
        self.assertIn('1 skipped', body)

    def test_ce_without_manage_staff_accounts_is_403(self):
        self.client.force_login(self.plain_ce)
        self.assertEqual(self.post('disable', self.staff_a).status_code, 403)
        self.assertTrue(self.active(self.staff_a))

    def test_own_account_is_skipped(self):
        self.client.force_login(self.manager)
        self.post('disable', self.manager)
        self.assertTrue(self.active(self.manager))

    def test_non_superuser_cannot_disable_superuser(self):
        self.client.force_login(self.manager)
        self.post('disable', self.other_super)
        self.assertTrue(self.active(self.other_super))

    def test_superuser_can_disable_superuser(self):
        self.client.force_login(self.superuser)
        self.post('disable', self.other_super)
        self.assertFalse(self.active(self.other_super))

    def test_non_ce_account_is_skipped(self):
        self.client.force_login(self.superuser)
        self.post('disable', self.student)
        self.assertTrue(self.active(self.student))

    def test_non_numeric_ids_are_skipped(self):
        self.client.force_login(self.manager)
        resp = self.post('disable', raw_ids=['abc', self.staff_a.id])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.active(self.staff_a))

    def test_disabled_account_has_no_usable_session(self):
        self.staff_a.is_active = False
        self.staff_a.save()
        self.staff_a.campus = {'manage_staff_accounts': 'Yes'}
        self.staff_a.save()
        # force_login bypasses authenticate(), like SAML does.
        self.client.force_login(self.staff_a)
        resp = self.client.get(reverse('cis:users'))
        self.assertEqual(resp.status_code, 302)

    # -- delete ---------------------------------------------------------------

    def test_manager_cannot_preflight_or_delete(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.post('delete_preflight', self.staff_a).status_code, 403)
        self.assertEqual(self.post('delete', self.staff_a).status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.staff_a.pk).exists())

    def test_preflight_is_read_only_and_lists_blockers(self):
        StudentNote.objects.create(note='n', createdby=self.staff_a,
                                   createdon=timezone.now())
        self.client.force_login(self.superuser)

        resp = self.post('delete_preflight', self.staff_a, self.teacher_staff)

        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertEqual(body['outcome'], 'modal')
        html = body['html']
        self.assertIn('will be deleted', html)
        self.assertIn('reassigned to you', html)
        self.assertIn('blocked', html)
        self.assertIn('cis.Teacher.user', html)
        # Only the deletable account is carried into the confirm form.
        self.assertIn(f'name="ids[]" value="{self.staff_a.id}"', html)
        self.assertNotIn(f'name="ids[]" value="{self.teacher_staff.id}"', html)
        self.assertTrue(User.objects.filter(pk=self.staff_a.pk).exists())

    def test_delete_removes_deletable_and_reports_blocked(self):
        note = StudentNote.objects.create(note='n', createdby=self.staff_a,
                                          createdon=timezone.now())
        self.client.force_login(self.superuser)

        resp = self.post('delete', self.staff_a, self.teacher_staff)

        body = self.message(resp)
        self.assertIn('1 account(s) deleted', body)
        self.assertIn('1 blocked', body)
        self.assertFalse(User.objects.filter(pk=self.staff_a.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.teacher_staff.pk).exists())
        note.refresh_from_db()
        self.assertEqual(note.createdby_id, self.superuser.id)

    def test_delete_skips_self_and_non_ce(self):
        self.client.force_login(self.superuser)
        self.post('delete', self.superuser, self.student)
        self.assertTrue(User.objects.filter(pk=self.superuser.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.student.pk).exists())

    # -- page -----------------------------------------------------------------

    def test_delete_button_only_rendered_for_superusers(self):
        self.client.force_login(self.manager)
        self.assertNotIn('delete_preflight', self.client.get(reverse('cis:users')).content.decode())

        self.client.force_login(self.superuser)
        page = self.client.get(reverse('cis:users')).content.decode()
        self.assertIn('delete_preflight', page)
        self.assertIn('disable', page)


class OldTenantSignatureTests(TestCase):
    """A tenant whose users_table.build_config predates bulk actions must not
    break (cis#18).

    The tenant table config is per-tenant in-tree, so a tenant can bump cis
    without porting its myce_tenant_configs copy. Passing bulk_actions to an
    older build_config raised TypeError -- a 500 on /ce/users for a tenant that
    had not adopted the feature. The page now renders without the bulk buttons
    instead, and the tenant opts in by accepting the two kwargs.
    """

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
        ce, _ = Group.objects.get_or_create(name='ce')
        cls.superuser = User.objects.create_superuser(
            username='oldsig_su', email='oldsig_su@example.com', password='x')
        cls.superuser.groups.add(ce)

    def test_build_config_kwargs_are_gated_on_the_tenant_signature(self):
        from cis.views.users import _supported_kwargs

        def old(*, variant, api_url, details_prefix='', filter_form_selector=None):
            pass

        def new(*, variant, api_url, details_prefix='', filter_form_selector=None,
                bulk_actions=None, bulk_actions_url=None):
            pass

        def catch_all(*, variant, api_url, **kwargs):
            pass

        payload = {'bulk_actions': {}, 'bulk_actions_url': '/x'}
        self.assertEqual(_supported_kwargs(old, payload), {})
        self.assertEqual(_supported_kwargs(new, payload), payload)
        self.assertEqual(_supported_kwargs(catch_all, payload), payload)

    def test_page_renders_when_tenant_config_predates_bulk_actions(self):
        from unittest import mock

        import cis.views.users as users_views

        real = users_views.build_users_table_config

        def old_signature(*, variant, api_url, details_prefix='',
                          filter_form_selector=None):
            return real(variant=variant, api_url=api_url,
                        details_prefix=details_prefix,
                        filter_form_selector=filter_form_selector)

        self.client.force_login(self.superuser)
        with mock.patch.object(users_views, 'build_users_table_config', old_signature):
            resp = self.client.get(reverse('cis:users'))

        self.assertEqual(resp.status_code, 200)
        page = resp.content.decode()
        self.assertNotIn('delete_preflight', page)
        self.assertIn('records_staff_users', page)
