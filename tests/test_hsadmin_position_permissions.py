"""Per-school HS admin permissions stored on HSAdministratorPosition.

Spec: docs/superpowers/specs/2026-10-07-hsadmin-position-permissions-design.md
"""
from unittest import mock

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase

from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdminPerm, HSAdministratorAccessRequest, HSAdministratorPosition,
    hsadmin_permission_objects)
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


class RoleFormPermissionTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def _render_edit(self, role):
        from cis.views.hs_administrator import add_new_role
        request = RequestFactory().get('/', {
            'id': str(role.id), 'parent': str(role.hsadmin_id), 'ajax': '1'})
        request.user = self.staff
        return add_new_role(request).content.decode()

    def _edit(self, role, permission_ids):
        from cis.forms.highschool import HSAdministratorPositionForm
        data = {
            'id': str(role.id), 'hs_admin': str(role.hsadmin_id), 'ajax': '1',
            'highschool': str(role.highschool_id), 'position': str(role.position_id),
            'status': 'Active', 'note': 'n', 'permissions': permission_ids,
        }
        form = HSAdministratorPositionForm(id=str(role.id), data=data)
        self.assertTrue(form.is_valid(), form.errors)
        request = RequestFactory().post('/')
        request.user = self.staff
        return form.save(request)

    def _ids(self, *codenames):
        return [str(p.pk) for p in hsadmin_permission_objects(codenames)]

    def test_renders_nine_checkboxes_with_current_ticked(self):
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)
        body = self._render_edit(self.role_a1)
        self.assertEqual(body.count('name="permissions"'), 9)
        self.assertIn('Can bulk enroll', body)
        self.assertNotIn('name="manage_student_recommendation"', body)
        checked = hsadmin_permission_objects([HSAdminPerm.BULK_ENROLL]).get()
        self.assertRegex(body, rf'value="{checked.pk}"[^>]*checked')

    def test_edit_sets_exactly_the_ticked_permissions(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        self._edit(self.role_a1, self._ids(HSAdminPerm.BULK_ENROLL, HSAdminPerm.VERIFY_ROSTER))
        self.assertEqual(self.role_a1.codenames(),
                         {HSAdminPerm.BULK_ENROLL, HSAdminPerm.VERIFY_ROSTER})

    def test_edit_with_nothing_ticked_clears(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        self._edit(self.role_a1, [])
        self.assertEqual(self.role_a1.codenames(), set())

    def test_new_role_defaults_to_nothing_ticked(self):
        from cis.forms.highschool import HSAdministratorPositionForm
        with mock.patch('cis.forms.highschool.picker_queryset',
                        return_value=HighSchool.objects.all()):
            form = HSAdministratorPositionForm(id='-1', initial={'id': '-1'})
        self.assertFalse(form['permissions'].value())
        self.assertFalse(form.fields['permissions'].required)


class AccessRequestPermissionTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.req = HSAdministratorAccessRequest.objects.create(
            name='Cara Gamma', email='cara@example.com', phone='1',
            highschool=self.central, role='Registrar', status='Submitted')
        patcher = mock.patch('cis.forms.highschool.picker_queryset',
                             return_value=HighSchool.objects.all())
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tear_down_fixture()

    def _form(self, user, **kwargs):
        from cis.forms.highschool import HSAdminAccessRequestModelForm
        request = RequestFactory().get('/')
        request.user = user
        return HSAdminAccessRequestModelForm(request=request, **kwargs)

    def _approve(self, codenames):
        data = {'name': self.req.name, 'email': self.req.email, 'phone': self.req.phone,
                'highschool': str(self.central.id), 'role': self.req.role,
                'status': 'Approved',
                'permissions': [str(p.pk) for p in hsadmin_permission_objects(codenames)]}
        form = self._form(self.staff, data=data, instance=self.req)
        self.assertTrue(form.is_valid(), form.errors)
        record = form.save()
        return record.grant_access(form.cleaned_data)

    def _new_role(self):
        return HSAdministratorPosition.objects.get(
            hsadmin__user__email='cara@example.com', highschool=self.central)

    def test_ce_sees_permissions_and_no_recommendation_select(self):
        form = self._form(self.staff, instance=self.req)
        self.assertIn('permissions', form.fields)
        self.assertNotIn('manage_student_recommendation', form.fields)
        self.assertFalse(form['permissions'].value())

    def test_public_form_has_no_permissions(self):
        from django.contrib.auth.models import AnonymousUser
        form = self._form(AnonymousUser())
        self.assertNotIn('permissions', form.fields)

    def test_approval_grants_exactly_the_ticked(self):
        self.assertTrue(self._approve([HSAdminPerm.BULK_ENROLL, HSAdminPerm.VERIFY_ROSTER]))
        self.assertEqual(self._new_role().codenames(),
                         {HSAdminPerm.BULK_ENROLL, HSAdminPerm.VERIFY_ROSTER})
        self.assertNotIn('manage_student_recommendation', self._new_role().meta)

    def test_approval_with_nothing_ticked_grants_nothing(self):
        self.assertTrue(self._approve([]))
        self.assertEqual(self._new_role().codenames(), set())

    def test_existing_role_is_not_changed(self):
        from cis.models.highschool_administrator import HSPosition
        self.assertTrue(self._approve([HSAdminPerm.BULK_ENROLL]))
        self.req.refresh_from_db()
        self.req.status = 'Submitted'
        self.req.save()
        self.assertFalse(self._approve([HSAdminPerm.SUBMIT_GRADES]))  # IntegrityError path
        self.assertEqual(self._new_role().codenames(), {HSAdminPerm.BULK_ENROLL})
        self.assertEqual(HSPosition.objects.filter(name__iexact='Registrar').count(), 1)

    def test_processed_request_shows_current_role_permissions_read_only(self):
        self._approve([HSAdminPerm.BULK_ENROLL])
        self._new_role().grant(HSAdminPerm.SUBMIT_GRADES)
        self.req.refresh_from_db()
        form = self._form(self.staff, instance=self.req)
        self.assertTrue(form.fields['permissions'].disabled)
        self.assertEqual(
            {str(v) for v in form['permissions'].value()},
            {str(pk) for pk in hsadmin_permission_objects(
                [HSAdminPerm.BULK_ENROLL, HSAdminPerm.SUBMIT_GRADES]).values_list('pk', flat=True)})

    def test_processed_request_without_a_role_hides_the_field(self):
        HSAdministratorAccessRequest.objects.filter(pk=self.req.pk).update(status='Denied')
        self.req.refresh_from_db()
        form = self._form(self.staff, instance=self.req)
        self.assertNotIn('permissions', form.fields)


class SerializerTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_permissions_serialize_as_codenames(self):
        from cis.serializers.highschool import HighSchoolAdministratorSerializer
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES, HSAdminPerm.BULK_ENROLL)
        data = HighSchoolAdministratorSerializer(self.role_a1).data
        self.assertEqual(data['permissions'],
                         [HSAdminPerm.BULK_ENROLL, HSAdminPerm.SUBMIT_GRADES])

    def test_eager_queryset_prefetches_permissions(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from cis.serializers.highschool import HighSchoolAdministratorSerializer
        from cis.views.eager import with_highschool_administrator_related
        for role in (self.role_a1, self.role_a2, self.role_b1):
            role.grant(HSAdminPerm.BULK_ENROLL)

        def count(n):
            qs = with_highschool_administrator_related(
                HSAdministratorPosition.objects.order_by('id'))[:n]
            with CaptureQueriesContext(connection) as ctx:
                HighSchoolAdministratorSerializer(qs, many=True).data
            return len(ctx.captured_queries)

        self.assertEqual(count(1), count(3))
