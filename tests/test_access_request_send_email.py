"""HSAdministratorAccessRequest.send_email: edited text and the old default path."""
from unittest import mock

from django.test import TestCase, override_settings

from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import HSAdministratorAccessRequest
from cis.models.settings import Setting

SETTINGS_KEY = 'cis.settings.access_request'


@override_settings(DEBUG=False)
class SendEmailTests(TestCase):
    def setUp(self):
        Setting.objects.create(key=SETTINGS_KEY, value={
            'approved_subject': 'Approved', 'approved_email': 'Hi {{name}} {{password_reset_link}}',
            'denied_subject': 'Denied', 'denied_email': 'Sorry {{name}}',
        })
        self.hs = HighSchool.objects.create(name='North High', code='NH')
        self.req = HSAdministratorAccessRequest.objects.create(
            name='Jane Doe', email='jane@example.com', phone='555',
            highschool=self.hs, role='Counselor', status='Approved')

    @mock.patch('cis.models.highschool_administrator.send_html_mail')
    @mock.patch.object(HSAdministratorAccessRequest, 'get_password_reset_link',
                       return_value='https://reset.example/xyz')
    def test_overrides_render_with_real_values(self, _link, send):
        self.req.send_email(subject='Welcome {{name}}',
                            body='{{name}} / {{email}} / {{highschool}} / {{role}} / {{password_reset_link}}')
        subject, text, _html, _from, to = send.call_args.args
        self.assertEqual(subject, 'Welcome Jane Doe')
        self.assertEqual(text, 'Jane Doe / jane@example.com / North High / Counselor / https://reset.example/xyz')
        self.assertEqual(to, ['jane@example.com'])

    @mock.patch('cis.models.highschool_administrator.send_html_mail')
    @mock.patch.object(HSAdministratorAccessRequest, 'get_password_reset_link',
                       return_value='https://reset.example/xyz')
    def test_default_path_unchanged(self, _link, send):
        self.req.send_email()
        subject, text, *_ = send.call_args.args
        self.assertEqual(subject, 'Approved')
        self.assertEqual(text, 'Hi Jane Doe https://reset.example/xyz')

    @mock.patch('cis.models.highschool_administrator.send_html_mail')
    def test_submitted_status_sends_nothing(self, send):
        self.req.status = 'Submitted'
        self.assertIsNone(self.req.send_email(subject='x', body='y'))
        send.assert_not_called()

    def test_email_context_with_explicit_link(self):
        ctx = self.req.email_context(reset_link='[password reset link]')
        self.assertEqual(ctx['password_reset_link'], '[password reset link]')
        self.assertEqual(ctx['highschool'], 'North High')
