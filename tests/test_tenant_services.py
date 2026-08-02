from django.test import TestCase, override_settings

from cis.services.tenant_services import get_tenant_service


class TenantServiceResolverTests(TestCase):
    def test_resolves_ethos_identity_to_tenant_app(self):
        mod = get_tenant_service('ethos_identity')
        self.assertEqual(mod.__name__, 'myce_tenant_configs.services.ethos_identity')
        for fn in (
            'get_alt_credential_type_id',
            'get_ethos_client',
            'lookup_ethos_person_for_student',
            'lookup_ethos_person_by_psid',
            'apply_ethos_identity',
            'apply_ethos_identity_by_psid',
        ):
            self.assertTrue(callable(getattr(mod, fn)), fn)

    def test_resolves_sis_importer_to_tenant_app(self):
        mod = get_tenant_service('sis_importer')
        self.assertEqual(mod.__name__, 'myce_tenant_configs.services.sis_importer')
        self.assertTrue(hasattr(mod.SISImporter, 'import_sections'))

    def test_unknown_module_raises(self):
        with self.assertRaises(ModuleNotFoundError):
            get_tenant_service('does_not_exist_xyz')

    @override_settings(TENANT_SERVICES_APP='myce_tenant_configs')
    def test_honors_the_setting(self):
        mod = get_tenant_service('ethos_identity')
        self.assertTrue(mod.__name__.startswith('myce_tenant_configs.'))
