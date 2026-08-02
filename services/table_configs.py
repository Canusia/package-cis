"""Resolve table-config services from the tenant-configured app.

Keeps cis decoupled from any one tenant's `myce_tenant_configs` app name. Cis
views call `get_table_config('sections_table').build_config(...)` and the
actual module is loaded from `settings.TABLE_CONFIGS_APP`.

Resolution happens at view-module import time; INSTALLED_APPS is loaded
before any view is imported, so no special ordering required.
"""
import importlib

from django.conf import settings


def get_table_config(module_name):
    """Return the named `_table` service module from the tenant app.

    Example:
        cfg_mod = get_table_config('sections_table')
        ctx = cfg_mod.build_config(variant='sections_index', api_url=...)
    """
    return importlib.import_module(
        f'{settings.TABLE_CONFIGS_APP}.services.{module_name}'
    )
