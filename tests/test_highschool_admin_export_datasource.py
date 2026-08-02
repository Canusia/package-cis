from django.test import TestCase

from cis.reports.highschool_admin_export import highschool_admin_export


class HSAdminExportShortcodesTest(TestCase):
    def test_recipient_columns_include_school_and_position_tokens(self):
        tokens = set(highschool_admin_export().recipient_columns().values())
        for token in ('FirstName', 'LastName', 'email', 'HighSchool', 'Position'):
            self.assertIn(token, tokens)
