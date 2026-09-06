"""Skip helpers for tests that need an optional tenant service module.

`cis.tests` ships in the wheel, so it runs on whichever tenant installs the
package. Every tenant has a `myce_tenant_configs` app, but its *contents* vary:
the eleven required seams are always there, while modules like
`ethos_identity`, `student_profile_form` or `pending_sis_mirror_table` exist
only on the tenants that use those features. nnu, for instance, ships none of
them.

A test that imports one unconditionally turns into a collection-time
ImportError on a tenant that lacks it — a red suite out of the box, which is
what ewu#42 is about. Guarding with these helpers keeps the seam genuinely
exercised where the tenant defines it, and quietly skipped where it does not.

Note this is deliberately *not* named `test_*`: the runner must not collect it.
"""
import importlib
import importlib.util
import unittest

from django.conf import settings


def tenant_service_module(module_name):
    """Import the tenant's service module, or return None when absent."""
    dotted = f'{settings.TENANT_SERVICES_APP}.services.{module_name}'
    try:
        if importlib.util.find_spec(dotted) is None:
            return None
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    try:
        return importlib.import_module(dotted)
    except ImportError:
        return None


def has_tenant_service(module_name):
    return tenant_service_module(module_name) is not None


def requires_tenant_service(module_name):
    """Skip the decorated test or TestCase where the tenant lacks the module.

        @requires_tenant_service('ethos_identity')
        class EthosLookupTests(TestCase):
            ...
    """
    return unittest.skipUnless(
        has_tenant_service(module_name),
        f'{settings.TENANT_SERVICES_APP} does not ship a '
        f'services.{module_name} module')
