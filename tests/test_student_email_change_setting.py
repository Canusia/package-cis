from django.http import HttpRequest
from django.test import TestCase

from cis.models.settings import Setting
from cis.settings.student_email_change import student_email_change, DEFAULTS, get_config


class StudentEmailChangeSettingTests(TestCase):
    def setUp(self):
        Setting.objects.filter(key=student_email_change.key).delete()

    def test_key(self):
        self.assertEqual(student_email_change.key, 'cis.settings.student_email_change')

    def test_from_db_empty_when_unset(self):
        self.assertEqual(student_email_change.from_db(), {})

    def test_install_writes_defaults(self):
        student_email_change(HttpRequest()).install()
        self.assertEqual(student_email_change.from_db(), DEFAULTS)

    def test_install_does_not_clobber_existing(self):
        Setting.objects.create(key=student_email_change.key, value={**DEFAULTS, 'verification_subject': 'Custom'})
        student_email_change(HttpRequest()).install()
        self.assertEqual(student_email_change.from_db()['verification_subject'], 'Custom')

    def test_defaults_reference_code(self):
        self.assertIn('{{code}}', DEFAULTS['verification_message'])

    def test_run_record_persists(self):
        request = HttpRequest()
        form = student_email_change(request, data={**DEFAULTS, 'confirmation_subject': 'Changed'})
        self.assertTrue(form.is_valid(), form.errors)
        form.run_record()
        self.assertEqual(student_email_change.from_db()['confirmation_subject'], 'Changed')

    def test_verification_message_requires_code(self):
        form = student_email_change(HttpRequest(), data={**DEFAULTS, 'verification_message': 'no code here'})
        self.assertFalse(form.is_valid())
        self.assertIn('verification_message', form.errors)

    def test_get_config_defaults_when_unset(self):
        conf = get_config()
        self.assertEqual(conf['code_ttl_minutes'], 15)
        self.assertEqual(conf['max_attempts'], 5)
        self.assertEqual(conf['resend_cooldown_seconds'], 60)
        self.assertEqual(conf['max_requests_per_day'], 5)

    def test_get_config_casts_limits_to_int(self):
        Setting.objects.create(key=student_email_change.key, value={
            **DEFAULTS, 'code_ttl_minutes': '30', 'max_attempts': '3', 'resend_cooldown_seconds': '120',
            'max_requests_per_day': '7'})
        conf = get_config()
        self.assertEqual(
            (conf['code_ttl_minutes'], conf['max_attempts'], conf['resend_cooldown_seconds'], conf['max_requests_per_day']),
            (30, 3, 120, 7))

    def test_limits_bounds_validated(self):
        for field, bad in (
                ('code_ttl_minutes', 0), ('max_attempts', 0), ('resend_cooldown_seconds', -1),
                ('max_requests_per_day', 0)):
            form = student_email_change(HttpRequest(), data={**DEFAULTS, field: bad})
            self.assertFalse(form.is_valid(), field)
            self.assertIn(field, form.errors)
