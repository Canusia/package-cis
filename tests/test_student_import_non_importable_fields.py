"""ewu#38 — the fields a tenant refuses to accept from a CSV upload are named
by the tenant, and the row form and the CSV schema derive them from one place.

Before the seam, `StudentImportRowForm.DROP_FIELDS` and
`StudentImportColumns.EXCLUDED` each hardcoded a list, and the two lists did
not agree — EXCLUDED carried `highschool`, DROP_FIELDS did not, and any tenant
field added to one could silently miss the other.
"""
from unittest.mock import patch

from django.test import TestCase

import cis.forms.student_profile as profile_mod
from cis.forms.student_import import StudentImportRowForm
from cis.services.importers.student_import_schema import StudentImportColumns


class TenantNonImportableFieldsAccessorTests(TestCase):

    def test_absent_export_defaults_to_empty(self):
        class _Bare:
            pass

        with patch.object(profile_mod, '_tenant_module', return_value=_Bare()):
            self.assertEqual(profile_mod.tenant_non_importable_fields(), ())

    def test_export_is_read_as_a_tuple(self):
        class _Tenant:
            NON_IMPORTABLE_FIELDS = ['no_ssn', 'agree_tuition_responsibility']

        with patch.object(profile_mod, '_tenant_module', return_value=_Tenant()):
            fields = profile_mod.tenant_non_importable_fields()
        self.assertEqual(fields, ('no_ssn', 'agree_tuition_responsibility'))
        self.assertIsInstance(fields, tuple)


class RowFormDropsNonImportableFieldsTests(TestCase):

    def _field_names(self):
        return set(StudentImportRowForm().fields)

    def test_generic_mechanic_fields_are_always_dropped(self):
        names = self._field_names()
        for name in ('password', 'confirm_password', 'verify_student_ssn',
                     'signature'):
            self.assertNotIn(name, names)

    def test_tenant_non_importable_field_is_dropped(self):
        target = next(n for n in ('gender', 'legal_sex', 'ethnicity')
                      if n in StudentImportRowForm().fields)
        with patch.object(profile_mod, 'tenant_non_importable_fields',
                          return_value=(target,)):
            self.assertNotIn(target, self._field_names())

    def test_naming_an_absent_field_is_harmless(self):
        with patch.object(profile_mod, 'tenant_non_importable_fields',
                          return_value=('not_a_real_field',)):
            self.assertIn('first_name', self._field_names())


class SchemaDerivesFromTheSameSourceTests(TestCase):
    """The drift guard: one accessor feeds both the form and the CSV columns."""

    def test_headers_exclude_the_tenant_non_importable_fields(self):
        target = next(n for n in ('gender', 'legal_sex', 'ethnicity')
                      if n in StudentImportColumns.headers())
        with patch.object(profile_mod, 'tenant_non_importable_fields',
                          return_value=(target,)):
            self.assertNotIn(target, StudentImportColumns.headers())

    def test_form_and_schema_agree_on_what_is_excluded(self):
        target = next(n for n in ('gender', 'legal_sex', 'ethnicity')
                      if n in StudentImportColumns.headers())
        with patch.object(profile_mod, 'tenant_non_importable_fields',
                          return_value=(target,)):
            self.assertNotIn(target, StudentImportColumns.headers())
            self.assertNotIn(target, set(StudentImportRowForm().fields))

    def test_highschool_is_still_represented_by_the_ceeb_column(self):
        headers = StudentImportColumns.headers()
        self.assertNotIn('highschool', headers)
        self.assertIn(StudentImportColumns.CEEB_COLUMN, headers)
