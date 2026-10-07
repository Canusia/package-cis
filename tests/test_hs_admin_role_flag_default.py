"""normalize_position_flag and migration 0099 (package-cis#72); role permissions
are tested in test_hsadmin_position_permissions.

HSAdministratorPositionForm once listed 'Yes' first with no initial, so a role
whose meta had no manage_student_recommendation rendered as 'Yes' and saving it
unchanged granted recommendation access. 0099 normalised the stored values;
0101 then moved them into position permissions.
"""
import importlib

from django.apps import apps as django_apps
from django.test import TestCase

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
