"""`get_tenant_service` resolves a module out of the configured tenant app.

The resolver is the mechanism; which modules a tenant ships is the tenant's
business. Assertions here name `settings.TENANT_SERVICES_APP` rather than
'myce_tenant_configs' literally, and the two module-specific cases skip on a
tenant that does not ship them — `ethos_identity` and `sis_importer` are opt-in
modules, not required seams (ewu#42).
"""
from django.conf import settings
from django.test import TestCase, override_settings

from cis.services.tenant_services import get_tenant_service
from cis.tests.tenant_support import requires_tenant_service


class TenantServiceResolverTests(TestCase):

    @requires_tenant_service('ethos_identity')
    def test_resolves_ethos_identity_to_tenant_app(self):
        mod = get_tenant_service('ethos_identity')
        self.assertEqual(
            mod.__name__,
            f'{settings.TENANT_SERVICES_APP}.services.ethos_identity')
        for fn in (
            'get_alt_credential_type_id',
            'get_ethos_client',
            'lookup_ethos_person_for_student',
            'lookup_ethos_person_by_psid',
            'apply_ethos_identity',
            'apply_ethos_identity_by_psid',
        ):
            self.assertTrue(callable(getattr(mod, fn)), fn)

    @requires_tenant_service('sis_importer')
    def test_resolves_sis_importer_to_tenant_app(self):
        mod = get_tenant_service('sis_importer')
        self.assertEqual(
            mod.__name__,
            f'{settings.TENANT_SERVICES_APP}.services.sis_importer')
        self.assertTrue(hasattr(mod.SISImporter, 'import_sections'))

    def test_resolves_a_required_seam_to_the_tenant_app(self):
        """highschool_types is one of the required seams, so every tenant has
        it — this is the resolver assertion that holds everywhere."""
        mod = get_tenant_service('highschool_types')
        self.assertEqual(
            mod.__name__,
            f'{settings.TENANT_SERVICES_APP}.services.highschool_types')

    def test_unknown_module_raises(self):
        with self.assertRaises(ModuleNotFoundError):
            get_tenant_service('does_not_exist_xyz')

    def test_honors_the_setting(self):
        with override_settings(TENANT_SERVICES_APP='cis.tests.fake_tenant'):
            mod = get_tenant_service('highschool_types')
        self.assertTrue(mod.__name__.startswith('cis.tests.fake_tenant.'))
