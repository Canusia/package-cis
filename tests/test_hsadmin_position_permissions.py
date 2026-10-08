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

    def test_renders_a_dual_list_with_current_chosen(self):
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)
        body = self._render_edit(self.role_a1)
        self.assertIn('id="id_permissions_duallist"', body)
        self.assertEqual(body.count('name="permissions"'), 1)
        start = body.index('id="id_permissions_duallist"')
        source = body[start:body.index('</select>', start)]
        self.assertEqual(source.count('<option value='), 9)
        self.assertIn('Can bulk enroll', body)
        self.assertNotIn('name="manage_student_recommendation"', body)
        chosen = hsadmin_permission_objects([HSAdminPerm.BULK_ENROLL]).get()
        self.assertRegex(body, rf'<option value="{chosen.pk}"[^>]*selected')

    def test_edit_sets_exactly_the_ticked_permissions(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        self._edit(self.role_a1, self._ids(HSAdminPerm.BULK_ENROLL, HSAdminPerm.VERIFY_ROSTER))
        self.assertEqual(self.role_a1.codenames(),
                         {HSAdminPerm.BULK_ENROLL, HSAdminPerm.VERIFY_ROSTER})

    def test_edit_with_nothing_ticked_clears(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        self._edit(self.role_a1, [])
        self.assertEqual(self.role_a1.codenames(), set())

    def test_hs_admin_does_not_see_permissions(self):
        """The HS admin portal's personnel 'Update Status' modal uses this
        form; only CE grants permissions (spec: Defaults)."""
        from cis.views.hs_administrator import add_new_role
        request = RequestFactory().get('/', {
            'id': str(self.role_a1.id), 'parent': str(self.role_a1.hsadmin_id), 'ajax': '1'})
        request.user = self.user_a
        body = add_new_role(request).content.decode()
        self.assertIn('name="status"', body)
        self.assertNotIn('name="permissions"', body)

    def test_hs_admin_post_cannot_change_permissions(self):
        from cis.views.hs_administrator import add_new_role
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        request = RequestFactory().post('/?ajax=1', {
            'id': str(self.role_a1.id), 'hs_admin': str(self.role_a1.hsadmin_id),
            'ajax': '1', 'highschool': str(self.central.id),
            'position': str(self.role_a1.position_id), 'status': 'Active', 'note': 'n',
            'permissions': self._ids(HSAdminPerm.BULK_ENROLL, HSAdminPerm.VERIFY_ROSTER),
        })
        request.user = self.user_a
        add_new_role(request)
        self.assertEqual(self.role_a1.codenames(), {HSAdminPerm.SUBMIT_GRADES})

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

    def test_processed_request_labels_the_field_as_current(self):
        self._approve([HSAdminPerm.BULK_ENROLL])
        self.req.refresh_from_db()
        form = self._form(self.staff, instance=self.req)
        self.assertEqual(form.fields['permissions'].label, 'Current role permissions')

    def test_denied_request_hides_the_field_even_if_the_role_exists(self):
        self._approve([HSAdminPerm.BULK_ENROLL])
        HSAdministratorAccessRequest.objects.filter(pk=self.req.pk).update(status='Denied')
        self.req.refresh_from_db()
        form = self._form(self.staff, instance=self.req)
        self.assertNotIn('permissions', form.fields)

    def test_single_campus_has_no_scope(self):
        self.assertNotIn('scope', self._form(self.staff, instance=self.req).fields)

    def test_approval_grants_for_the_chosen_campus(self):
        from django.conf import settings as djs
        from django.test import override_settings as ovs
        from cis.models.course import Campus as C
        from cis.models.highschool import HighSchoolCampus as HSC
        lit = C.objects.create(name='LIT Z', code=f'{djs.CAMPUS_CODE_PREFIX}_LITZ')
        HSC.objects.create(highschool=self.central, campus=lit)
        data = {'name': self.req.name, 'email': self.req.email, 'phone': self.req.phone,
                'highschool': str(self.central.id), 'role': self.req.role, 'status': 'Approved',
                'scope': str(lit.id),
                'permissions': [str(p.pk) for p in hsadmin_permission_objects([HSAdminPerm.BULK_ENROLL])]}
        with ovs(MULTI_CAMPUS=True):
            form = self._form(self.staff, data=data, instance=self.req)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertTrue(form.save().grant_access(form.cleaned_data))
        self.assertEqual(self._new_role().grants(), [(HSAdminPerm.BULK_ENROLL, lit)])

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
                         [{'codename': HSAdminPerm.BULK_ENROLL, 'campus': None},
                          {'codename': HSAdminPerm.SUBMIT_GRADES, 'campus': None}])

    def test_campus_grant_serializes_campus_code(self):
        from django.conf import settings as djs
        from cis.models.course import Campus as C
        from cis.serializers.highschool import HighSchoolAdministratorSerializer
        lit = C.objects.create(name='LIT S', code=f'{djs.CAMPUS_CODE_PREFIX}_LITS')
        self.role_a1.grant(HSAdminPerm.VERIFY_ROSTER, campus=lit)
        self.assertEqual(HighSchoolAdministratorSerializer(self.role_a1).data['permissions'],
                         [{'codename': HSAdminPerm.VERIFY_ROSTER, 'campus': lit.code}])

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


import uuid as _uuid  # noqa: E402
from django.conf import settings as dj_settings  # noqa: E402
from cis.models.course import Campus  # noqa: E402
from cis.models.highschool import HighSchoolCampus  # noqa: E402,F401


class CampusGrantTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        p = dj_settings.CAMPUS_CODE_PREFIX
        self.lit = Campus.objects.create(name=f'LIT {_uuid.uuid4().hex[:4]}', code=f'{p}_L{_uuid.uuid4().hex[:4]}')
        self.lsc = Campus.objects.create(name=f'LSC {_uuid.uuid4().hex[:4]}', code=f'{p}_S{_uuid.uuid4().hex[:4]}')

    def tearDown(self):
        self.tear_down_fixture()

    def test_all_campuses_grant_counts_everywhere(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        for campus in (None, self.lit, self.lsc):
            self.assertTrue(self.role_a1.has_perm(HSAdminPerm.SUBMIT_GRADES, campus))

    def test_campus_grant_counts_only_for_that_campus(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES, campus=self.lit)
        self.assertTrue(self.role_a1.has_perm(HSAdminPerm.SUBMIT_GRADES, self.lit))
        self.assertFalse(self.role_a1.has_perm(HSAdminPerm.SUBMIT_GRADES, self.lsc))
        self.assertFalse(self.role_a1.has_perm(HSAdminPerm.SUBMIT_GRADES))
        self.assertTrue(self.admin_a.has_school_perm(HSAdminPerm.SUBMIT_GRADES, self.central.id, self.lit))
        self.assertFalse(self.admin_a.has_school_perm(HSAdminPerm.SUBMIT_GRADES, self.central.id, self.lsc))

    def test_any_campus(self):
        from cis.models.highschool_administrator import ANY_CAMPUS
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES, campus=self.lsc)
        self.assertEqual(list(self.admin_a.highschools_with_perm(HSAdminPerm.SUBMIT_GRADES, ANY_CAMPUS)),
                         [self.central])
        self.assertEqual(list(self.admin_a.highschools_with_perm(HSAdminPerm.SUBMIT_GRADES)), [])

    def test_union_is_not_duplicated_and_revoke_is_per_scope(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES, campus=self.lit)
        self.assertEqual(HSAdministratorPosition.objects.with_perm(
            HSAdminPerm.SUBMIT_GRADES, self.lit).count(), 1)
        self.role_a1.revoke(HSAdminPerm.SUBMIT_GRADES, campus=self.lit)
        self.assertEqual(self.role_a1.grants(), [(HSAdminPerm.SUBMIT_GRADES, None)])

    def test_set_perms_replaces_one_scope_only(self):
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES, campus=self.lit)
        self.role_a1.set_perms([HSAdminPerm.VERIFY_ROSTER], campus=self.lit)
        self.assertEqual(sorted(self.role_a1.grants(), key=str),
                         sorted([(HSAdminPerm.BULK_ENROLL, None),
                                 (HSAdminPerm.VERIFY_ROSTER, self.lit)], key=str))

    def test_codenames_by_scope(self):
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL)
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES, campus=self.lit)
        self.assertEqual(self.role_a1.codenames(), {HSAdminPerm.BULK_ENROLL})
        self.assertEqual(self.role_a1.codenames(self.lit),
                         {HSAdminPerm.BULK_ENROLL, HSAdminPerm.SUBMIT_GRADES})

    def test_prefetched_grants_not_stale(self):
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL, campus=self.lit)
        role = HSAdministratorPosition.objects.prefetch_related(
            'permission_grants__permission__content_type', 'permission_grants__campus'
        ).get(pk=self.role_a1.pk)
        self.assertEqual(role.grants(), [(HSAdminPerm.BULK_ENROLL, self.lit)])
        role.revoke(HSAdminPerm.BULK_ENROLL, campus=self.lit)
        self.assertEqual(role.grants(), [])

    def test_administrators_in_highschool_by_campus(self):
        self.role_a1.grant(HSAdminPerm.VERIFY_ROSTER, campus=self.lit)
        self.assertEqual(list(self.central.administrators_in_highschool(
            'can_verify_roster', campus=self.lit)), [self.admin_a])
        self.assertEqual(list(self.central.administrators_in_highschool(
            'can_verify_roster', campus=self.lsc)), [])

    def test_wrappers_take_campus(self):
        self.role_a1.grant(HSAdminPerm.VERIFY_ROSTER, campus=self.lit)
        self.assertTrue(self.admin_a.can_verify_roster(self.central.id, campus=self.lit))
        self.assertFalse(self.admin_a.can_verify_roster(self.central.id, campus=self.lsc))
        self.assertEqual(list(self.admin_a.get_roster_highschools(campus=self.lit)), [self.central])


from django.test import override_settings  # noqa: E402
from cis.campus_context import campus_context as campus_ctx  # noqa: E402


class RoleFormScopeTests(HsAdminRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        p = dj_settings.CAMPUS_CODE_PREFIX
        self.lit = Campus.objects.create(name='LIT X', code=f'{p}_LITX')
        self.lsc = Campus.objects.create(name='LSC X', code=f'{p}_LSCX')
        HighSchoolCampus.objects.create(highschool=self.central, campus=self.lit)

    def tearDown(self):
        self.tear_down_fixture()

    def _form(self, data=None, **kw):
        from cis.forms.highschool import HSAdministratorPositionForm
        return HSAdministratorPositionForm(id=str(self.role_a1.id), data=data, **kw)

    def _data(self, scope='', perms=()):
        return {'id': str(self.role_a1.id), 'hs_admin': str(self.role_a1.hsadmin_id), 'ajax': '1',
                'highschool': str(self.central.id), 'position': str(self.role_a1.position_id),
                'status': 'Active', 'note': 'n', 'scope': scope,
                'permissions': [str(p.pk) for p in hsadmin_permission_objects(perms)]}

    def _save(self, form):
        self.assertTrue(form.is_valid(), form.errors)
        request = RequestFactory().post('/')
        request.user = self.staff
        form.save(request)

    def test_single_campus_has_no_scope_and_ignores_posted_scope(self):
        self.assertNotIn('scope', self._form(initial={'id': str(self.role_a1.id),
                                                       'highschool': self.central.id}).fields)
        self._save(self._form(self._data(scope=str(self.lit.id), perms=[HSAdminPerm.BULK_ENROLL])))
        self.assertEqual(self.role_a1.grants(), [(HSAdminPerm.BULK_ENROLL, None)])

    @override_settings(MULTI_CAMPUS=True)
    def test_scope_choices_are_the_schools_campuses(self):
        form = self._form(initial={'id': str(self.role_a1.id), 'highschool': self.central.id})
        self.assertEqual(list(form.fields['scope'].queryset), [self.lit])

    @override_settings(MULTI_CAMPUS=True)
    def test_save_replaces_only_the_chosen_scope(self):
        self.role_a1.grant(HSAdminPerm.SUBMIT_GRADES)
        self._save(self._form(self._data(scope=str(self.lit.id), perms=[HSAdminPerm.BULK_ENROLL])))
        self.assertEqual(sorted(self.role_a1.grants(), key=str), sorted(
            [(HSAdminPerm.SUBMIT_GRADES, None), (HSAdminPerm.BULK_ENROLL, self.lit)], key=str))

    @override_settings(MULTI_CAMPUS=True)
    def test_unlinked_campus_is_rejected(self):
        form = self._form(self._data(scope=str(self.lsc.id), perms=[HSAdminPerm.BULK_ENROLL]))
        self.assertFalse(form.is_valid())
        self.assertIn('scope', form.errors)

    @override_settings(MULTI_CAMPUS=True)
    def test_invalid_post_rerender_keeps_the_scope_map(self):
        # Review fix: after a validation error the 'Applies to' switch must
        # still know each scope's grants, or saving could wipe one.
        from cis.views.hs_administrator import add_new_role
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL, campus=self.lit)
        data = self._data(scope=str(self.lit.id), perms=[HSAdminPerm.BULK_ENROLL])
        data['note'] = ''                      # required -> invalid
        request = RequestFactory().post('/', data)
        request.user = self.staff
        with campus_ctx(self.lit):
            body = add_new_role(request).content.decode()
        self.assertIn('data-scope-grants', body)
        self.assertIn(str(self.lit.id), body.split('data-scope-grants')[1][:400])

    @override_settings(MULTI_CAMPUS=True)
    def test_render_carries_every_scopes_grants(self):
        from cis.views.hs_administrator import add_new_role
        self.role_a1.grant(HSAdminPerm.BULK_ENROLL, campus=self.lit)
        request = RequestFactory().get('/', {'id': str(self.role_a1.id),
                                             'parent': str(self.role_a1.hsadmin_id), 'ajax': '1'})
        request.user = self.staff
        with campus_ctx(self.lit):
            body = add_new_role(request).content.decode()
        self.assertIn('name="scope"', body)
        self.assertIn('data-scope-grants', body)
        self.assertIn(str(self.lit.id), body)
