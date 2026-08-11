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


def get_tenant_override(module_name, attr):
    """Return `attr` from a tenant service module, or None if not overridden.

    The opt-in form of `get_tenant_service`, for seams where `cis` keeps a
    working default and a tenant may replace it: a tenant that ships neither the
    module nor the attribute simply gets the default. Callers do

        override = get_tenant_override('registration', 'needs_recommendation')
        if override is not None:
            return override(self)

    Call this from inside the function that needs it, not at module import time
    — tenant service modules import `cis.models.*` at their own module level, so
    resolving one while a `cis` model module is still importing risks
    AppRegistryNotReady.

    A missing tenant module yields None; an ImportError raised from *inside* one
    is a real breakage and propagates rather than being swallowed into the
    default, which would hide the failure behind plausible behaviour.
    """
    try:
        module = get_tenant_service(module_name)
    except ModuleNotFoundError as exc:
        app = settings.TENANT_SERVICES_APP
        if exc.name in (f'{app}.services.{module_name}', f'{app}.services', app):
            return None
        raise
    return getattr(module, attr, None)
