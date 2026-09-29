from django.test import TestCase
from cis.services.importers.student_import_schema import StudentImportColumns


class StudentImportColumnsTests(TestCase):
    def test_core_required_columns_present(self):
        required = StudentImportColumns.required()
        for col in ('first_name', 'last_name', 'email', 'highschool_ceeb'):
            self.assertIn(col, required)

    def test_password_and_hidden_fields_excluded(self):
        headers = StudentImportColumns.headers()
        for col in ('password', 'confirm_password', 'verify_student_ssn',
                    'highschool', 'county', 'signature'):
            self.assertNotIn(col, headers)

    def test_ceeb_replaces_highschool(self):
        headers = StudentImportColumns.headers()
        self.assertIn('highschool_ceeb', headers)

    def test_columns_follow_the_tenant_form(self):
        """Every importable field on the tenant's form is a column, and is
        required exactly when the form requires it. Asserted over whatever
        form the tenant declares rather than by field name, so it holds on
        every tenant (ewu#42)."""
        headers = StudentImportColumns.headers()
        required = set(StudentImportColumns.required())
        excluded = StudentImportColumns.excluded()
        importable = {
            name: field
            for name, field in StudentImportColumns._form_fields().items()
            if name not in excluded and not StudentImportColumns._is_hidden(field)
        }
        self.assertTrue(importable, 'the tenant form declares no importable fields')
        for name, field in importable.items():
            with self.subTest(field=name):
                self.assertIn(name, headers)
                self.assertEqual(name in required, field.required)
