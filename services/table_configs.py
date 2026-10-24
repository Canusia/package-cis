"""Resolve table-config services from the tenant-configured app.

Keeps cis decoupled from any one tenant's `myce_tenant_configs` app name. Cis
views call `get_table_config('sections_table').build_config(...)` and the
actual module is loaded from `settings.TABLE_CONFIGS_APP`.

Resolution happens per request, never when a views module is imported
(package-cis#97): a module-level `get_table_config(...)` call made one missing
tenant module an ImportError for the whole cis URLconf. Views that keep a
module-level builder use `lazy_table_config`, which defers the import to the
first call, so a tenant that lacks a table config loses only that page.
"""
import importlib
import inspect

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


# Table configs cis renders with no fallback: a tenant missing one gets an
# error on that page (system check cis.W010 names it at startup).
REQUIRED_TABLE_CONFIGS = (
    'academic_years_table',
    'access_requests_table',
    'cohorts_table',
    'course_app_requirements_table',
    'course_document_requirements_table',
    'courses_table',
    'credentials_table',
    'districts_table',
    'faculty_coords_table',
    'faculty_dangling_table',
    'faculty_table',
    'highschools_table',
    'hs_admin_dangling_table',
    'hs_admin_people_table',
    'hs_admins_table',
    'hs_roles_table',
    'instructor_dangling_table',
    'instructors_table',
    'locked_users_table',
    'pending_sis_mirror_table',
    'registrations_table',
    'sections_table',
    'student_dangling_table',
    'student_notes_table',
    'student_recommendations_table',
    'students_table',
    'support_docs_table',
    'terms_table',
    'users_table',
)

# Table configs whose page falls back (plain list, or the tab is hidden) when
# the tenant does not ship them. Each has its own check: W002, W003, W005,
# W007, W008.
OPTIONAL_TABLE_CONFIGS = (
    'document_types_table',
    'hs_uploads_table',
    'login_log_table',
    'roleless_users_table',
    'saml_log_table',
)


def table_configs_app():
    return getattr(settings, 'TABLE_CONFIGS_APP', 'myce_tenant_configs')


class MissingTableConfig(ModuleNotFoundError, ImproperlyConfigured):
    """The tenant app does not ship the requested table-config module.

    A ModuleNotFoundError whose `name` is the missing module, so callers that
    treat an absent optional config as "not adopted" keep working, and an
    ImproperlyConfigured whose message says what to add.
    """


def get_table_config(module_name):
    """Return the named `_table` service module from the tenant app.

    Example:
        cfg_mod = get_table_config('sections_table')
        ctx = cfg_mod.build_config(variant='sections_index', api_url=...)

    Raises MissingTableConfig when the tenant app does not ship the module. An
    ImportError raised from *inside* a module that exists propagates as is.
    """
    app = table_configs_app()
    dotted = f'{app}.services.{module_name}'
    try:
        return importlib.import_module(dotted)
    except ModuleNotFoundError as exc:
        if exc.name not in (dotted, f'{app}.services', app):
            raise
        raise MissingTableConfig(
            f'Table config {dotted} is missing. cis has no default for it: ship '
            f'services/{module_name}.py in {app} (with its template and JS; '
            f'copy them from Canusia/ewu myce_tenant_configs) or set '
            f'TABLE_CONFIGS_APP to an app that has it.',
            name=dotted,
        ) from exc


class lazy_table_config:
    """A module-level stand-in for `get_table_config(name).<attr>`.

    `build_x = lazy_table_config('x_table')` keeps the old call shape
    (`build_x(variant=..., api_url=...)`) but imports the tenant module on the
    first call rather than when the views module is imported (#97).
    `inspect.signature(build_x)` reports the real function's signature.
    """

    def __init__(self, module_name, attr='build_config'):
        self.module_name = module_name
        self.attr = attr
        self.__name__ = f'{module_name}.{attr}'

    def resolve(self):
        return getattr(get_table_config(self.module_name), self.attr)

    def __call__(self, *args, **kwargs):
        return self.resolve()(*args, **kwargs)

    @property
    def __signature__(self):
        return inspect.signature(self.resolve())

    def __repr__(self):
        return f'<lazy_table_config {self.module_name}.{self.attr}>'
