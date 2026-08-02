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

    def test_optional_field_is_optional(self):
        # preferred_name is required=False in the form
        self.assertIn('preferred_name', StudentImportColumns.headers())
        self.assertNotIn('preferred_name', StudentImportColumns.required())
