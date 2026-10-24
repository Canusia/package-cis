"""Resolve tenant-specific integration service modules from the configured app.

Keeps cis — and shared packages like `ethos` — decoupled from any one tenant's
app name. Callers do `get_tenant_service('ethos_identity').apply_ethos_identity(...)`
and the actual module is loaded from `settings.TENANT_SERVICES_APP`.

`TENANT_SERVICES_APP` defaults to `TABLE_CONFIGS_APP` when a host leaves it
unset (#97): both name the tenant's `myce_tenant_configs`-style app, and a
missing setting used to be an AttributeError at startup.

Mirrors `cis.services.table_configs.get_table_config`, which resolves presentation
table-config modules from `settings.TABLE_CONFIGS_APP`.
"""
import importlib

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def tenant_services_app():
    """The app tenant service modules resolve from, read at call time so
    override_settings reaches it."""
    return (getattr(settings, 'TENANT_SERVICES_APP', None)
            or getattr(settings, 'TABLE_CONFIGS_APP', None)
            or 'myce_tenant_configs')


class MissingTenantService(ModuleNotFoundError, ImproperlyConfigured):
    """The tenant app does not ship the requested service module.

    Still a ModuleNotFoundError whose `name` is the missing module, so callers
    that treat absence as "not adopted" keep working; the message says what to
    add.
    """


def get_tenant_service(module_name):
    """Return the named service module from the tenant-configured app.

    Example:
        svc = get_tenant_service('ethos_identity')
        changes, error = svc.apply_ethos_identity(student, person, actor=user)

    Raises MissingTenantService when the tenant app does not ship the module.
    An ImportError raised from *inside* a module that exists propagates as is.
    """
    app = tenant_services_app()
    dotted = f'{app}.services.{module_name}'
    try:
        return importlib.import_module(dotted)
    except ModuleNotFoundError as exc:
        if exc.name not in (dotted, f'{app}.services', app):
            raise
        raise MissingTenantService(
            f'Tenant service module {dotted} is missing: ship '
            f'services/{module_name}.py in {app} (see the package-cis README, '
            f'"Required tenant service modules"), or point TENANT_SERVICES_APP '
            f'at an app that has it.',
            name=dotted,
        ) from exc


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
    except MissingTenantService as exc:
        if exc.name == f'{tenant_services_app()}.services.{module_name}':
            return None
        raise
    return getattr(module, attr, None)
