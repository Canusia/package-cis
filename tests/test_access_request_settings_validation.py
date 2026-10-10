"""Access-request Settings: broken approval/denial templates can't be saved."""
from django.test import RequestFactory, TestCase

from cis.settings.access_request import access_request


class AccessRequestSettingsValidationTests(TestCase):
    def form(self, **overrides):
        data = {
            'submitted_subject': 'New request', 'submitted_email': 'From {{name}}',
            'submitted_internal_notification': 'staff@example.com',
            'approved_subject': 'Welcome {{name}}',
            'approved_email': 'Set your password: {{password_reset_link}}',
            'denied_subject': 'About your request', 'denied_email': 'Sorry {{name}}',
        }
        data.update(overrides)
        request = RequestFactory().get('/x', {'report_id': '1'})
        return access_request(request, data=data)

    def test_valid_templates_save(self):
        self.assertTrue(self.form().is_valid(), self.form().errors)

    def test_typo_in_approved_email_rejected(self):
        form = self.form(approved_email='Hi {{nmae}} {{password_reset_link}}')
        self.assertFalse(form.is_valid())
        self.assertIn('Did you mean {{name}}?', str(form.errors['approved_email']))

    def test_reset_link_not_allowed_in_denial(self):
        form = self.form(denied_email='{{password_reset_link}}')
        self.assertFalse(form.is_valid())
        self.assertIn('only be used in an approval email', str(form.errors['denied_email']))

    def test_subjects_validated_too(self):
        form = self.form(approved_subject='Welcome {name}')
        self.assertFalse(form.is_valid())
        self.assertIn('approved_subject', form.errors)

    def test_approved_email_without_reset_link_rejected(self):
        form = self.form(approved_email='Welcome {{name}}')
        self.assertFalse(form.is_valid())
        self.assertIn('password_reset_link', str(form.errors['approved_email']))
