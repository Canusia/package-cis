from unittest.mock import patch
from django.test import SimpleTestCase

from cis.forms.application_spec import (
    get_application_fields, get_application_rules, get_tenant_post_save,
    get_tenant_validator)


class SpecLoaderTests(SimpleTestCase):
    def test_returns_none_when_no_tenant_module(self):
        # Asserted against a *simulated* absent module, not against ewu
        # shipping none: the day a tenant arms a spec this must still hold.
        with patch('cis.forms.application_spec.importlib.import_module',
                   side_effect=ModuleNotFoundError):
            self.assertIsNone(get_application_fields())

    def test_returns_list_when_module_present(self):
        import types
        mod = types.ModuleType('fake_app.services.application_form')
        mod.APPLICATION_FIELDS = [{'name': 'x', 'type': 'text', 'label': 'X',
                                   'required': False, 'target': 'meta'}]
        with patch('cis.forms.application_spec.importlib.import_module', return_value=mod):
            self.assertEqual(get_application_fields()[0]['name'], 'x')

    def test_rules_and_validator_default_to_empty_without_a_tenant_module(self):
        with patch('cis.forms.application_spec.importlib.import_module',
                   side_effect=ModuleNotFoundError):
            self.assertEqual(get_application_rules(), [])
            self.assertEqual(get_tenant_validator(), (None, frozenset()))
            self.assertIsNone(get_tenant_post_save())

    def test_rules_and_validator_come_from_the_tenant_module(self):
        import types
        mod = types.ModuleType('fake_app.services.application_form')
        mod.APPLICATION_RULES = [{'rule': 'match',
                                  'fields': ['password', 'confirm_password']}]
        mod.validate = lambda form, cleaned_data: None
        mod.VALIDATE_FIELDS = ['permanent_address', 'county']

        with patch('cis.forms.application_spec.importlib.import_module', return_value=mod):
            self.assertEqual(get_application_rules()[0]['rule'], 'match')
            validate, owned = get_tenant_validator()
            self.assertIs(validate, mod.validate)
            self.assertEqual(owned, frozenset({'permanent_address', 'county'}))

    def test_a_tenant_module_without_rules_or_validator_is_fine(self):
        import types
        mod = types.ModuleType('fake_app.services.application_form')
        mod.APPLICATION_FIELDS = []

        with patch('cis.forms.application_spec.importlib.import_module', return_value=mod):
            self.assertEqual(get_application_rules(), [])
            self.assertEqual(get_tenant_validator(), (None, frozenset()))
