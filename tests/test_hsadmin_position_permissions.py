"""Per-school HS admin permissions stored on HSAdministratorPosition.

Spec: docs/superpowers/specs/2026-10-07-hsadmin-position-permissions-design.md
"""
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from cis.models.highschool import HighSchool  # noqa: F401  (used by later tests)
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


class AdministratorPermissionTests(HsAdminRoleFixtureMixin, TestCase):
    """role_a1 = admin_a @ Central (Active), role_a2 = admin_a @ North (Active),
    role_b1 = admin_b @ Central (Inactive)."""

    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_has_school_perm_is_per_school(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        self.assertTrue(self.admin_a.has_school_perm(HSAdminPerm.SUBMIT_GRADES, self.central.id))
        self.assertFalse(self.admin_a.has_school_perm(HSAdminPerm.SUBMIT_GRADES, self.north.id))
        self.assertEqual(list(self.admin_a.highschools_with_perm(HSAdminPerm.SUBMIT_GRADES)),
                         [self.central])

    def test_falsy_school_is_refused(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        for value in (None, ''):
            self.assertFalse(self.admin_a.has_school_perm(HSAdminPerm.SUBMIT_GRADES, value))

    def test_inactive_and_lowercase_status_grant_nothing(self):
        self.role_b1.grant(HSAdminPerm.VERIFY_ROSTER)
        self.assertFalse(self.admin_b.can_verify_roster(self.central.id))
        HSAdministratorPosition.objects.filter(pk=self.role_b1.pk).update(status='active')
        self.assertFalse(self.admin_b.can_verify_roster(self.central.id))
        self.assertFalse(self.central.administrators_in_highschool(
            status='can_verify_roster').exists())

    def test_wrappers_follow_permissions(self):
        self.role_a1.grant(HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION, HSAdminPerm.VERIFY_ROSTER)
        self.assertTrue(self.admin_a.can_manage_student_recommendation(self.central.id))
        self.assertTrue(self.admin_a.can_manage_student_student_recommendation(self.central.id))
        self.assertTrue(self.admin_a.can_verify_roster(self.central.id))
        self.assertEqual(list(self.admin_a.get_recommendation_highschools()), [self.central])
        self.assertEqual(list(self.admin_a.get_roster_highschools()), [self.central])
        self.assertEqual(
            list(self.central.administrators_in_highschool(status='can_verify_roster')),
            [self.admin_a])
        self.assertEqual(
            list(self.central.administrators_in_highschool(
                status='can_manage_student_recommendation')),
            [self.admin_a])

    def test_meta_flags_are_no_longer_read(self):
        HSAdministratorPosition.objects.filter(pk=self.role_a1.pk).update(
            meta={'manage_student_recommendation': 'Yes', 'manage_roster_verification': 'Yes'})
        self.assertFalse(self.admin_a.can_manage_student_recommendation(self.central.id))
        self.assertFalse(self.admin_a.can_verify_roster(self.central.id))

    def test_toggle_student_recommendation(self):
        self.role_a1.toggle_student_recommendation()
        self.assertTrue(self.role_a1.has_perm(HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION))
        self.role_a1.toggle_student_recommendation()
        self.assertFalse(self.role_a1.has_perm(HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION))


class LifecycleTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_deactivation_keeps_permissions_and_meta(self):
        self.role_a1.meta = {'other': 'kept'}
        self.role_a1.save()
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)
        self.role_a1.status = 'Inactive'
        self.role_a1.save()
        self.role_a1.refresh_from_db()
        self.assertEqual(self.role_a1.codenames(), {HSAdminPerm.BULK_ENROLL})
        self.assertFalse(self.role_a1.has_perm(HSAdminPerm.BULK_ENROLL))
        self.assertEqual(self.role_a1.meta, {'other': 'kept'})

    def test_reactivation_restores_access(self):
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)
        self.role_a1.toggle_status()
        self.role_a1.toggle_status()
        self.assertTrue(self.admin_a.has_school_perm(HSAdminPerm.BULK_ENROLL, self.central.id))

    def test_get_or_add_creates_with_no_permissions_and_no_flags(self):
        role = HSAdministratorPosition.get_or_add(
            self.admin_b, self.north, self.principal, 'Active')
        self.assertEqual(role.codenames(), set())
        self.assertEqual(role.meta, {})
