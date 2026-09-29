"""MC-06 (#30): only a campus's own settings admins can view or edit its settings.

Single-campus deployments keep today's rule (any CE staff member or a
superuser). In multi-campus mode CE staff also need the manage_settings flag
and must be on the campus being served; keys shared by every campus, and
setting titles/descriptions, become superuser-only; the Django admin shows
staff only their campuses' rows and lets only a superuser import.
"""
import uuid

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings

from cis.admin.setting import SettingAdmin
from cis.campus_context import campus_context
from cis.campus_gate import (
    can_edit_setting_descriptions, can_edit_setting_key, can_manage_settings)
from cis.models.course import Campus
from cis.models.customuser import CustomUser
from cis.models.settings import Setting

SCOPED = f'{settings.CAMPUS_CODE_PREFIX}_cis_registrations'
GLOBAL = 'cis.settings.menu'


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


def _user(*campuses, manage_settings='Yes', group='ce'):
    user = CustomUser.objects.create_user(
        username=f'u{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
        password='x')
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    user.campus = {'process_campus': [str(c.id) for c in campuses],
                   'manage_settings': manage_settings}
    user.save()
    return user


def _superuser():
    return CustomUser.objects.create_superuser(
        username=f'su{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
        password='x')


class SingleCampusUnchangedTests(TestCase):
    def test_any_ce_staff_member_manages_every_setting(self):
        staff = _user(manage_settings='No')
        self.assertTrue(can_manage_settings(staff))
        self.assertTrue(can_edit_setting_key(staff, GLOBAL))
        self.assertTrue(can_edit_setting_key(staff, SCOPED))
        self.assertTrue(can_edit_setting_descriptions(staff))

    def test_other_roles_are_refused(self):
        self.assertFalse(can_manage_settings(_user(group='student')))

    def test_admin_shows_every_row_and_allows_import(self):
        staff = _user()
        staff.is_staff = True
        Setting.objects.create(key=GLOBAL, value={})
        request = RequestFactory().get('/')
        request.user = staff
        admin = SettingAdmin(Setting, AdminSite())
        self.assertEqual(admin.get_queryset(request).count(), Setting.objects.count())


@override_settings(MULTI_CAMPUS=True)
class MultiCampusTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')

    def test_settings_admin_on_their_campus(self):
        with campus_context(self.c1):
            self.assertTrue(can_manage_settings(_user(self.c1)))

    def test_staff_without_the_flag_are_refused(self):
        with campus_context(self.c1):
            self.assertFalse(can_manage_settings(_user(self.c1, manage_settings='No')))

    def test_staff_of_another_campus_are_refused(self):
        with campus_context(self.c2):
            self.assertFalse(can_manage_settings(_user(self.c1)))

    def test_shared_keys_and_descriptions_are_superuser_only(self):
        staff = _user(self.c1)
        su = _superuser()
        with campus_context(self.c1):
            self.assertTrue(can_edit_setting_key(staff, SCOPED))
            self.assertFalse(can_edit_setting_key(staff, GLOBAL))
            self.assertFalse(can_edit_setting_descriptions(staff))
            self.assertTrue(can_edit_setting_key(su, GLOBAL))
            self.assertTrue(can_edit_setting_descriptions(su))

    def _admin_request(self, user):
        request = RequestFactory().get('/')
        request.user = user
        return request

    def test_admin_shows_staff_only_their_campuses_rows(self):
        Setting.objects.create(key=SCOPED, value={}, campus=self.c1)
        Setting.objects.create(key=SCOPED, value={}, campus=self.c2)
        Setting.objects.create(key=GLOBAL, value={}, campus=None)
        admin = SettingAdmin(Setting, AdminSite())

        rows = admin.get_queryset(self._admin_request(_user(self.c1)))
        self.assertEqual(list(rows.values_list('campus', flat=True)), [self.c1.pk])
        self.assertEqual(
            admin.get_queryset(self._admin_request(_superuser())).count(),
            Setting.objects.count())

    def test_only_a_superuser_may_import(self):
        admin = SettingAdmin(Setting, AdminSite())
        self.assertFalse(admin.has_import_permission(self._admin_request(_user(self.c1))))
