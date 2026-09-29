"""School Type handling in the high school CSV importer.

Pinned to the fake tenant (cis/tests/fake_tenant/services/highschool_types.py):
the vocabulary is tenant-owned, so asserting one tenant's codes made this red
everywhere else (ewu#42).
"""
from django.test import TestCase, override_settings

from cis.services.importers.highschool_schema import HighSchoolRow


def _validate_hs_type(value):
    return HighSchoolRow.validate_hs_type(value)


@override_settings(TENANT_SERVICES_APP='cis.tests.fake_tenant')
class ValidateHsTypeTests(TestCase):
    def test_accepts_a_code(self):
        self.assertEqual(_validate_hs_type('type_a'), 'type_a')

    def test_accepts_a_label(self):
        """Spreadsheets predating the code/label split carry labels."""
        self.assertEqual(_validate_hs_type('Type A'), 'type_a')

    def test_is_case_and_whitespace_insensitive(self):
        self.assertEqual(_validate_hs_type('  type b '), 'type_b')

    def test_splits_semicolon_separated_multi_value(self):
        """hs_type is multi-valued; ';' separates, because ',' is both the CSV
        delimiter and MultiSelectField's internal separator."""
        self.assertEqual(_validate_hs_type('Type A; Type C'), 'type_a;type_c')

    def test_none_passes_through(self):
        self.assertIsNone(_validate_hs_type(None))

    def test_unknown_value_raises_and_lists_the_valid_ones(self):
        with self.assertRaises(ValueError) as ctx:
            _validate_hs_type('Public')

        message = str(ctx.exception)
        self.assertIn('Public', message)
        self.assertIn('Type A', message)

    def test_one_bad_token_in_a_multi_value_raises(self):
        with self.assertRaises(ValueError):
            _validate_hs_type('Type A; Nonsense')
