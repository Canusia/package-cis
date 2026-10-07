"""Per-school HS admin permissions stored on HSAdministratorPosition.

Spec: docs/superpowers/specs/2026-10-07-hsadmin-position-permissions-design.md
"""
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from cis.models.highschool_administrator import (
    HSAdminPerm, HSAdministratorPosition, hsadmin_permission_objects)
from cis.tests.test_hs_admin_roles_tab import HsAdminRoleFixtureMixin


class PositionPermissionApiTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_all_nine_permissions_exist(self):
        self.assertEqual(
            [p.codename for p in hsadmin_permission_objects(HSAdminPerm.ALL)],
            list(HSAdminPerm.ALL))
        self.assertEqual(len(HSAdminPerm.ALL), 9)

    def test_unknown_codename_is_rejected(self):
        with self.assertRaises(ValueError):
            hsadmin_permission_objects(['view_hsadministratorposition'])

    def test_new_position_has_no_permissions(self):
        self.assertEqual(self.role_a1.codenames(), set())
        self.assertFalse(self.role_a1.has_perm(HSAdminPerm.BULK_ENROLL))

    def test_set_grant_revoke(self):
        self.role_a1.set_perms([HSAdminPerm.BULK_ENROLL, HSAdminPerm.SUBMIT_GRADES])
        self.assertEqual(self.role_a1.codenames(),
                         {HSAdminPerm.BULK_ENROLL, HSAdminPerm.SUBMIT_GRADES})
        self.role_a1.grant(HSAdminPerm.VERIFY_ROSTER)
        self.role_a1.revoke(HSAdminPerm.SUBMIT_GRADES)
        self.assertEqual(self.role_a1.codenames(),
                         {HSAdminPerm.BULK_ENROLL, HSAdminPerm.VERIFY_ROSTER})
        self.role_a1.set_perms([])
        self.assertEqual(self.role_a1.codenames(), set())

    def test_has_perm_needs_exact_active(self):
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)
        self.assertTrue(self.role_a1.has_perm(HSAdminPerm.BULK_ENROLL))
        for status in ('Inactive', 'active'):
            with self.subTest(status=status):
                HSAdministratorPosition.objects.filter(pk=self.role_a1.pk).update(status=status)
                self.role_a1.refresh_from_db()
                self.assertFalse(self.role_a1.has_perm(HSAdminPerm.BULK_ENROLL))
                self.assertEqual(self.role_a1.codenames(), {HSAdminPerm.BULK_ENROLL})

    def test_with_perm(self):
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)
        self.role_b1.grant(HSAdminPerm.BULK_ENROLL)  # Inactive
        self.assertEqual(
            list(HSAdministratorPosition.objects.with_perm(HSAdminPerm.BULK_ENROLL)),
            [self.role_a1])

    def test_same_codename_from_another_content_type_is_ignored(self):
        other_ct = ContentType.objects.get_for_model(Permission)
        imposter = Permission.objects.create(
            content_type=other_ct, codename=HSAdminPerm.SUBMIT_GRADES, name='x')
        self.role_a1.permissions.add(imposter)
        self.assertEqual(self.role_a1.codenames(), set())
        self.assertFalse(self.role_a1.has_perm(HSAdminPerm.SUBMIT_GRADES))
        self.assertFalse(
            HSAdministratorPosition.objects.with_perm(HSAdminPerm.SUBMIT_GRADES).exists())

    def test_codenames_not_stale_after_set_perms_on_prefetched_row(self):
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)
        role = HSAdministratorPosition.objects.prefetch_related(
            'permissions').get(pk=self.role_a1.pk)
        self.assertEqual(role.codenames(), {HSAdminPerm.BULK_ENROLL})
        role.set_perms([HSAdminPerm.SUBMIT_GRADES])
        self.assertEqual(role.codenames(), {HSAdminPerm.SUBMIT_GRADES})
