"""The skip helpers that keep `cis.tests` green on a tenant without a module.

`cis.tests` ships in the wheel, so it runs against whatever
`myce_tenant_configs` the installing tenant has. Optional service modules
(`ethos_identity`, `student_profile_form`, `pending_sis_mirror_table`, ...)
exist on some tenants and not others, and a test that imports one
unconditionally turns into a collection-time ImportError there (ewu#42).
"""
import unittest

from django.conf import settings
from django.test import TestCase

from cis.tests.tenant_support import (
    has_tenant_service, requires_tenant_service, tenant_service_module)


class TenantSupportTests(TestCase):

    def test_a_required_seam_is_present(self):
        """highschool_types is one of the required seams, so every tenant has
        it -- including whichever one is running this."""
        self.assertTrue(has_tenant_service('highschool_types'))
        self.assertIsNotNone(tenant_service_module('highschool_types'))

    def test_an_absent_module_reports_missing_rather_than_raising(self):
        self.assertFalse(has_tenant_service('does_not_exist_xyz'))
        self.assertIsNone(tenant_service_module('does_not_exist_xyz'))

    def test_the_decorator_skips_when_the_module_is_absent(self):
        ran = []

        class Probe(TestCase):
            @requires_tenant_service('does_not_exist_xyz')
            def test_body(inner):
                ran.append(True)

        result = unittest.TextTestRunner(
            stream=open('/dev/null', 'w'), verbosity=0).run(
                unittest.TestLoader().loadTestsFromName('test_body', Probe))

        self.assertEqual(ran, [])
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])

    def test_the_decorator_runs_the_test_when_the_module_is_present(self):
        """The guard must not cost the coverage it guards."""
        ran = []

        class Probe(TestCase):
            @requires_tenant_service('highschool_types')
            def test_body(inner):
                ran.append(True)

        result = unittest.TextTestRunner(
            stream=open('/dev/null', 'w'), verbosity=0).run(
                unittest.TestLoader().loadTestsFromName('test_body', Probe))

        self.assertEqual(ran, [True])
        self.assertEqual(result.skipped, [])

    def test_the_skip_reason_names_the_tenant_app_and_module(self):
        """A skip nobody can explain is as bad as a failure."""

        class Probe(TestCase):
            @requires_tenant_service('does_not_exist_xyz')
            def test_body(inner):
                pass

        result = unittest.TextTestRunner(
            stream=open('/dev/null', 'w'), verbosity=0).run(
                unittest.TestLoader().loadTestsFromName('test_body', Probe))
        _, message = result.skipped[0]
        self.assertIn(settings.TENANT_SERVICES_APP, message)
        self.assertIn('does_not_exist_xyz', message)
