"""Migration 0101 copies the two legacy meta flags into permissions, and only those."""
import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from cis.models.highschool_administrator import HSAdminPerm, HSAdministratorPosition
from cis.tests.test_hs_admin_roles_tab import HsAdminRoleFixtureMixin

REC = 'manage_student_recommendation'
ROSTER = 'manage_roster_verification'


class BackfillTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.migration = importlib.import_module(
            'cis.migrations.0101_hsadmin_permissions_backfill')

    def tearDown(self):
        self.tear_down_fixture()

    def _meta(self, role, meta):
        HSAdministratorPosition.objects.filter(pk=role.pk).update(meta=meta)

    def test_forward_copies_only_yes_flags(self):
        self._meta(self.role_a1, {REC: 'Yes', ROSTER: 'yes'})
        self._meta(self.role_a2, {REC: 'No', ROSTER: ' YES '})
        self._meta(self.role_b1, {REC: 'odd', 'x': 1})

        self.migration.forward(django_apps, None)

        self.assertEqual(self.role_a1.codenames(),
                         {HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION, HSAdminPerm.VERIFY_ROSTER})
        self.assertEqual(self.role_a2.codenames(), {HSAdminPerm.VERIFY_ROSTER})
        self.assertEqual(self.role_b1.codenames(), set())

    def test_inactive_role_keeps_its_flags(self):
        self._meta(self.role_b1, {REC: 'Yes'})  # role_b1 is Inactive
        self.migration.forward(django_apps, None)
        self.assertEqual(self.role_b1.codenames(), {HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION})

    def test_forward_grants_none_of_the_new_permissions(self):
        self._meta(self.role_a1, {REC: 'Yes', ROSTER: 'Yes'})
        self.migration.forward(django_apps, None)
        new = set(HSAdminPerm.ALL) - {HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION,
                                      HSAdminPerm.VERIFY_ROSTER}
        for role in HSAdministratorPosition.objects.all():
            self.assertFalse(role.codenames() & new, role)

    def test_forward_is_idempotent(self):
        self._meta(self.role_a1, {REC: 'Yes'})
        self.migration.forward(django_apps, None)
        self.migration.forward(django_apps, None)
        self.assertEqual(self.role_a1.permissions.count(), 1)

    def test_non_dict_meta_is_skipped(self):
        self._meta(self.role_a1, [])
        self.migration.forward(django_apps, None)
        self.assertEqual(self.role_a1.codenames(), set())

    def test_backward_restores_meta_and_clears_permissions(self):
        self._meta(self.role_a1, {REC: 'yes', 'other': 'kept'})
        self.migration.forward(django_apps, None)
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)

        self.migration.backward(django_apps, None)

        self.role_a1.refresh_from_db()
        self.assertEqual(self.role_a1.meta[REC], 'Yes')
        self.assertEqual(self.role_a1.meta[ROSTER], 'No')
        self.assertEqual(self.role_a1.meta['other'], 'kept')
        self.assertEqual(self.role_a1.permissions.count(), 0)
