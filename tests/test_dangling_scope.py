"""Dangling-accounts bulk actions touch only accounts the tab lists: never a
superuser, never a roleless account outside the role's group, never the
requester (ewu#99). One case per role."""
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.tests.test_student_role_revocation import (
    _disconnect_login_signal, _reconnect_login_signal,
)

ROLES = (
    ('student', 'cis:student_do_dangling_bulk_action'),
    ('instructor', 'cis:instructor_do_dangling_bulk_action'),
    ('faculty', 'cis:faculty_do_dangling_bulk_action'),
    ('highschool_admin', 'cis:hs_admin_do_dangling_bulk_action'),
)


class DanglingScopeTests(TestCase):

    def setUp(self):
        self._receivers = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.ce_user = CustomUser.objects.create_user(
            username='scope_ce', email='scope_ce@example.com', password='x')
        self.ce_user.groups.add(ce_group)
        # Both actions need can_edit_users (cis#114 item 7).
        self.ce_user.campus = {'manage_staff_accounts': 'Yes'}
        self.ce_user.save()
        self.client.force_login(self.ce_user)

    def tearDown(self):
        _reconnect_login_signal(self._receivers)

    def _user(self, name, group=None, superuser=False):
        make = CustomUser.objects.create_superuser if superuser else CustomUser.objects.create_user
        user = make(username=name, email=f'{name}@example.com', password='x')
        if group:
            user.groups.add(Group.objects.get_or_create(name=group)[0])
        return user

    def _post(self, url, action, *users):
        return self.client.post(reverse(url), {
            'action': action, 'ids[]': [str(u.id) for u in users]})

    def test_delete_never_removes_a_superuser_with_no_groups(self):
        for group, url in ROLES:
            with self.subTest(role=group):
                su = self._user(f'su_{group}', superuser=True)
                self._post(url, 'delete_account', su)
                self.assertTrue(CustomUser.objects.filter(pk=su.pk).exists())

    def test_delete_never_removes_a_superuser_in_the_group(self):
        for group, url in ROLES:
            with self.subTest(role=group):
                su = self._user(f'sug_{group}', group=group, superuser=True)
                self._post(url, 'delete_account', su)
                self.assertTrue(CustomUser.objects.filter(pk=su.pk).exists())

    def test_delete_never_removes_a_roleless_account_outside_the_group(self):
        for group, url in ROLES:
            with self.subTest(role=group):
                roleless = self._user(f'none_{group}')
                self._post(url, 'delete_account', roleless)
                self.assertTrue(CustomUser.objects.filter(pk=roleless.pk).exists())

    def test_delete_still_removes_a_listed_dangling_account(self):
        for group, url in ROLES:
            with self.subTest(role=group):
                dangling = self._user(f'dangle_{group}', group=group)
                self._post(url, 'delete_account', dangling)
                self.assertFalse(CustomUser.objects.filter(pk=dangling.pk).exists())

    def test_revoke_never_touches_a_superuser_in_the_group(self):
        for group, url in ROLES:
            with self.subTest(role=group):
                su = self._user(f'rsu_{group}', group=group, superuser=True)
                self._post(url, 'revoke_access', su)
                self.assertTrue(su.groups.filter(name=group).exists())

    def test_requester_is_never_acted_on(self):
        for group, url in ROLES:
            with self.subTest(role=group):
                self.ce_user.groups.add(Group.objects.get_or_create(name=group)[0])
                self._post(url, 'revoke_access', self.ce_user)
                self.assertTrue(self.ce_user.groups.filter(name=group).exists())

    def test_ids_not_on_the_tab_are_reported(self):
        for group, url in ROLES:
            with self.subTest(role=group):
                su = self._user(f'msg_{group}', superuser=True)
                resp = self._post(url, 'delete_account', su)
                self.assertIn('1 not on this tab', resp.json()['message'])
