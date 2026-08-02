"""PT-16: stored XSS in the two-step verification page via the
``verification_page_header`` setting.

Fix = (a) remove ``|safe`` on the header rendering in
``two_step/verify.html`` so Django auto-escapes, AND (b) sanitize the
stored value with ``cis.utils.sanitize_plain_text`` on the setting save
path so no HTML/JS markup is ever persisted. The view also sanitizes at
read time as defense-in-depth.
"""
from django.test import TestCase

from cis.settings.two_step import two_step as TwoStepSettingForm


class TwoStepSettingSanitizeTests(TestCase):
    def _to_python_with(self, header):
        form = TwoStepSettingForm.__new__(TwoStepSettingForm)
        form.cleaned_data = {
            'mode': 'active',
            'email_subject': 'Subject',
            'email_message': 'Hi {{first_name}}',
            'text_message': 'Code {{verification_code}}',
            'verification_page_header': header,
        }
        return form._to_python()

    def test_strips_img_onerror_payload(self):
        out = self._to_python_with(
            'Welcome <img src=x onerror=console.log(916253)>'
        )['verification_page_header']
        self.assertNotIn('<', out)
        self.assertNotIn('>', out)
        self.assertNotIn('onerror', out)

    def test_strips_script_and_malformed_markup(self):
        for payload in [
            '<script>alert(1)</script>',
            '<svg onload=alert(1)>',
            '<img src=x onerror="alert(1)"',  # unclosed / malformed
        ]:
            out = self._to_python_with(payload)['verification_page_header']
            self.assertNotIn('<', out)
            self.assertNotIn('>', out)

    def test_preserves_placeholders_and_text(self):
        # The legitimate template placeholders contain no angle brackets,
        # so they must survive sanitization intact.
        out = self._to_python_with(
            'A code was sent to {{phone_last4}} and {{email_address}}.'
        )['verification_page_header']
        self.assertIn('{{phone_last4}}', out)
        self.assertIn('{{email_address}}', out)
        self.assertIn('A code was sent to', out)

    def test_other_fields_unchanged(self):
        result = self._to_python_with('plain header')
        self.assertEqual(result['mode'], 'active')
        self.assertEqual(result['email_subject'], 'Subject')
        self.assertEqual(result['email_message'], 'Hi {{first_name}}')
        self.assertEqual(result['text_message'], 'Code {{verification_code}}')


from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.settings import Setting
from cis.settings.two_step import two_step as _two_step_form

User = get_user_model()


class TwoStepVerifyRenderTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.user = User.objects.create_user(
            username='victim_pt16', email='victim_pt16@example.com',
            password='x', first_name='Vic', last_name='Tim',
        )
        # primary_phone is sliced ([-4:]) in the view; give it a value.
        if hasattr(self.user, 'primary_phone'):
            self.user.primary_phone = '5551234567'
            self.user.save(update_fields=['primary_phone'])

    def _store_header(self, header):
        # Persist via the model directly under the two_step setting key.
        Setting.objects.update_or_create(
            key=_two_step_form.key,
            defaults={'value': {
                'mode': 'active',
                'email_subject': 'S',
                'email_message': 'M',
                'text_message': 'T',
                'verification_page_header': header,
            }},
        )

    def test_injected_payload_is_escaped_in_response(self):
        # Simulate a *pre-fix* unsanitized value already in the DB; the
        # view's read-time sanitization + auto-escape must neutralize it.
        self._store_header(
            '<p>Welcome</p><img src=x onerror=alert(916253)>'
        )
        self.client.force_login(self.user)
        resp = self.client.get('/two_step/verify')
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The injected event handler / canary must not survive at all
        # (the base template legitimately contains a <img> logo, so we
        # assert on the unique injected markers, not on "<img" broadly).
        self.assertNotIn('onerror', body)
        self.assertNotIn('alert(916253)', body)
        # The injected <p> tag must not appear as live markup.
        self.assertNotIn('<p>', body)
        # The harmless leftover text is present and contains no live tag.
        self.assertIn('Welcome', body)

    def test_ordinary_header_text_preserved(self):
        self._store_header('A code was sent to your phone and email.')
        self.client.force_login(self.user)
        resp = self.client.get('/two_step/verify')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('A code was sent to your phone and email.',
                      resp.content.decode())
