"""The SIS-registration mirroring logic is tenant-specific and lives in the
tenant service app, resolved via get_tenant_service('registration'). This
verifies the module loads and exposes the expected callables. Behavioral
coverage lives in test_mirror_eligibility (which calls through the service).
"""
from django.test import TestCase

from cis.services.tenant_services import get_tenant_service


class RegistrationServiceResolutionTests(TestCase):
    def test_module_resolves_and_exposes_mirror_to_sis(self):
        mod = get_tenant_service('registration')
        self.assertTrue(callable(getattr(mod, 'mirror_to_sis', None)))

    def test_module_exposes_record_helpers(self):
        mod = get_tenant_service('registration')
        for name in ('_record_mirror_success',
                     '_record_mirror_failure',
                     '_record_ineligible'):
            self.assertTrue(
                callable(getattr(mod, name, None)),
                msg=f'{name} should be a module-level callable')
