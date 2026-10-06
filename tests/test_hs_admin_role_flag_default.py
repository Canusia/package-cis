"""An unset role permission flag reads and saves as 'No' (package-cis#72).

HSAdministratorPositionForm listed 'Yes' first with no initial, so a role whose
meta had no manage_student_recommendation (or held 'yes' in another casing)
rendered as 'Yes' in the edit form, and saving it unchanged granted
recommendation access -- while every access check treats unset as 'No'.
"""
import importlib

from django.apps import apps as django_apps
from django.test import RequestFactory, TestCase

from cis.forms.highschool import HSAdministratorPositionForm
from cis.models.highschool_administrator import (
    HSAdministratorPosition, normalize_position_flag)
from cis.tests.test_hs_admin_roles_tab import HsAdminRoleFixtureMixin


class NormalizePositionFlagTests(TestCase):
    def test_values(self):
        for value, expected in (
                (None, 'No'), ('', 'No'), ('No', 'No'), ('no', 'No'),
                ('Yes', 'Yes'), ('yes', 'Yes'), (' YES ', 'Yes'), ('maybe', 'No')):
            with self.subTest(value=value):
                self.assertEqual(normalize_position_flag(value), expected)


class RoleFormDefaultTests(HsAdminRoleFixtureMixin, TestCase):
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

    def _selected(self, body):
        start = body.index('name="manage_student_recommendation"')
        select = body[start:body.index('</select>', start)]
        return [opt for opt in ('Yes', 'No')
                if f'value="{opt}" selected' in select]

    def test_new_role_form_defaults_to_no(self):
        form = HSAdministratorPositionForm(id='-1', initial={'id': '-1'})
        field = form.fields['manage_student_recommendation']
        self.assertEqual(field.initial, 'No')
        self.assertEqual(field.choices[0][0], 'No')

    def test_unset_flag_renders_as_no(self):
        self.role_a1.meta = {}
        self.role_a1.save()
        self.assertEqual(self._selected(self._render_edit(self.role_a1)), ['No'])

    def test_lowercase_yes_renders_as_yes(self):
        self.role_a1.meta = {'manage_student_recommendation': 'yes'}
        self.role_a1.save()
        self.assertEqual(self._selected(self._render_edit(self.role_a1)), ['Yes'])

    def test_get_or_add_creates_the_role_with_no(self):
        role = HSAdministratorPosition.get_or_add(
            self.admin_b, self.north, self.principal, 'Active')
        self.assertEqual(role.meta.get('manage_student_recommendation'), 'No')

    def test_deactivating_keeps_other_meta_keys(self):
        self.role_a1.meta = {'manage_student_recommendation': 'Yes', 'other': 'kept'}
        self.role_a1.save()
        self.role_a1.status = 'Inactive'
        self.role_a1.save()
        self.role_a1.refresh_from_db()
        self.assertEqual(self.role_a1.meta.get('manage_student_recommendation'), 'No')
        self.assertEqual(self.role_a1.meta.get('other'), 'kept')

    def test_toggle_treats_lowercase_yes_as_yes(self):
        self.role_a1.meta = {'manage_student_recommendation': 'yes'}
        self.role_a1.save()
        self.role_a1.toggle_student_recommendation()
        self.role_a1.refresh_from_db()
        self.assertEqual(self.role_a1.meta['manage_student_recommendation'], 'No')


class BackfillMigrationTests(HsAdminRoleFixtureMixin, TestCase):
    """The data migration normalises stored values the same way."""

    def setUp(self):
        self.build_fixture()
        self.migration = importlib.import_module(
            'cis.migrations.0099_default_manage_student_recommendation')

    def tearDown(self):
        self.tear_down_fixture()

    def test_backfill(self):
        cases = {
            self.role_a1: ({}, 'No'),
            self.role_a2: ({'manage_student_recommendation': 'yes'}, 'Yes'),
            self.role_b1: ({'manage_student_recommendation': 'odd', 'x': 1}, 'odd'),
        }
        # .update(): stored data as it stands, without the save() signals.
        for role, (meta, _expected) in cases.items():
            HSAdministratorPosition.objects.filter(pk=role.pk).update(meta=meta)

        self.migration.normalise_flags(django_apps, None)

        for role, (_meta, expected) in cases.items():
            role.refresh_from_db()
            self.assertEqual(role.meta.get('manage_student_recommendation'), expected)
        self.assertEqual(self.role_b1.meta.get('x'), 1)
