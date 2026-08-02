from django.test import SimpleTestCase
from django import forms
from cis.forms.application_fields import build_fields


class FieldTypeTests(SimpleTestCase):
    def _one(self, entry):
        built = build_fields(entry)
        self.assertEqual(len(built), 1)
        return built[0]

    def test_text_field_carries_storage_metadata(self):
        name, field = self._one({'name': 'nickname', 'type': 'text', 'label': 'Nick',
                                  'required': True, 'target': 'meta'})
        self.assertEqual(name, 'nickname')
        self.assertIsInstance(field, forms.CharField)
        self.assertTrue(field.required)
        self.assertEqual(field.label, 'Nick')
        self.assertEqual(field.storage_target, 'meta')

    def test_email_field(self):
        _, field = self._one({'name': 'e', 'type': 'email', 'label': 'E',
                              'required': True, 'target': 'user', 'attr': 'secondary_email'})
        self.assertIsInstance(field, forms.EmailField)
        self.assertEqual(field.storage_target, 'user')
        self.assertEqual(field.storage_path, 'secondary_email')

    def test_choice_and_multichoice(self):
        _, c = self._one({'name': 'c', 'type': 'choice', 'label': 'C', 'required': True,
                          'target': 'meta', 'choices': ['A', 'B']})
        self.assertEqual(list(c.choices), [('A', 'A'), ('B', 'B')])
        _, m = self._one({'name': 'm', 'type': 'multichoice', 'label': 'M', 'required': True,
                          'target': 'meta', 'choices': ['A', 'B']})
        self.assertIsInstance(m, forms.MultipleChoiceField)

    def test_agreement_is_required_boolean_with_text_label(self):
        _, field = self._one({'name': 'agree', 'type': 'agreement',
                              'label': 'I agree to X', 'required': True, 'target': 'meta'})
        self.assertIsInstance(field, forms.BooleanField)
        self.assertTrue(field.required)
        self.assertEqual(field.label, 'I agree to X')

    def test_readonly_disclosure_is_skip_target(self):
        _, field = self._one({'name': 'ssn_disclosure', 'type': 'readonly_disclosure',
                              'label': '', 'required': False, 'target': 'skip',
                              'text': 'Privacy Act notice...'})
        self.assertFalse(field.required)
        self.assertEqual(field.storage_target, 'skip')
        self.assertIn('Privacy Act', str(field.initial))

    def test_unknown_type_raises(self):
        with self.assertRaises(KeyError):
            build_fields({'name': 'x', 'type': 'nope', 'label': 'X',
                          'required': False, 'target': 'meta'})
