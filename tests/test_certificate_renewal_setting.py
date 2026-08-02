from django.test import TestCase

from cis.settings.teacher_certificate_renewal import teacher_certificate_renewal


class CertificateRenewalSettingTest(TestCase):
    def test_from_db_returns_empty_dict_when_unset(self):
        self.assertEqual(teacher_certificate_renewal.from_db(), {})

    def test_install_then_from_db_returns_defaults(self):
        teacher_certificate_renewal(None).install()
        self.assertEqual(
            teacher_certificate_renewal.from_db().get('is_active'),
            'Debug',
        )
