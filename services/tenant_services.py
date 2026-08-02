"""Resolve tenant-specific integration service modules from the configured app.

Keeps cis — and shared packages like `ethos` — decoupled from any one tenant's
app name. Callers do `get_tenant_service('ethos_identity').apply_ethos_identity(...)`
and the actual module is loaded from `settings.TENANT_SERVICES_APP`.

Mirrors `cis.services.table_configs.get_table_config`, which resolves presentation
table-config modules from `settings.TABLE_CONFIGS_APP`.
"""
import importlib

from django.conf import settings


def get_tenant_service(module_name):
    """Return the named service module from the tenant-configured app.

    Example:
        svc = get_tenant_service('ethos_identity')
        changes, error = svc.apply_ethos_identity(student, person, actor=user)
    """
    return importlib.import_module(
        f'{settings.TENANT_SERVICES_APP}.services.{module_name}'
    )
