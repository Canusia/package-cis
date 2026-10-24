"""The one place ``cis`` resolves the ``ethos`` (Banner/Ethos SIS) app.

WHY THIS MODULE EXISTS
----------------------
``ethos`` is optional (#85, #114 item 1): a tenant without Banner/Ethos (nnu)
deploys cis with no ethos app at all. cis used to import ethos at module level
in ``actions/term.py`` -- which ``views/term.py`` imports, so all of
``cis.urls`` failed -- and in two management commands, and migration 0056 plus
``StudentRegistration.mirror_logs`` pointed at ``ethos.EthosLog``.

Rules for future work:

* Do not add ``from ethos…`` / ``import ethos`` anywhere else in ``cis``; go
  through the helpers below, which return ``None`` (or a safe default) when
  ethos is absent.
* Imports of ethos modules happen lazily, inside the helpers, so neither app
  loading order nor the app's absence can break ``cis`` import.

Two facts are tracked separately:

* ``ETHOS_INSTALLED`` -- the ethos code is importable (flat pip layout
  ``ethos`` or the editable submodule ``ethos.ethos``). Resolved once, at
  import. ``find_spec('ethos')`` is checked first: ``find_spec('ethos.ethos')``
  imports the parent and raises ``ModuleNotFoundError`` when it is missing.
* ``ethos_enabled()`` -- the code is importable **and** an app labelled
  ``ethos`` is in ``INSTALLED_APPS``. This is what callers want: ethos code
  touches ethos models, which cannot load without the app.
"""

import importlib
import importlib.util
from functools import wraps

__all__ = [
    'ETHOS_APP_LABEL',
    'ETHOS_INSTALLED',
    'ETHOS_MISSING_MESSAGE',
    'ETHOS_ROOT',
    'ethos_app_installed',
    'ethos_client_class',
    'ethos_enabled',
    'ethos_log_model',
    'ethos_module',
    'ethos_not_configured_error',
    'import_sections_task',
    'requires_ethos',
]

ETHOS_APP_LABEL = 'ethos'

ETHOS_MISSING_MESSAGE = (
    'This needs the Ethos SIS integration (the ethos app), which is not '
    'installed on this site.')


def _detect_ethos_root():
    """Return the importable root package of ethos, or None when absent."""
    try:
        if importlib.util.find_spec('ethos') is None:
            return None
    except (ImportError, AttributeError, ValueError):
        return None
    try:
        if importlib.util.find_spec('ethos.ethos') is not None:
            return 'ethos.ethos'
    except (ImportError, AttributeError, ValueError):
        pass
    return 'ethos'


ETHOS_ROOT = _detect_ethos_root()

#: True when the ethos code is importable in either layout.
ETHOS_INSTALLED = ETHOS_ROOT is not None


class _EthosUnavailable(Exception):
    """Stand-in for ``ethos.credentials.EthosNotConfigured`` when ethos is
    absent. Never raised; it lets ``except`` clauses stay unconditional."""


def ethos_app_installed():
    """True when an app labelled ``ethos`` is in INSTALLED_APPS.

    Safe from model class bodies (all app configs exist before any models
    module is imported) and from migration modules."""
    from django.apps import apps
    return ETHOS_APP_LABEL in apps.app_configs


def ethos_enabled():
    """True when ethos is importable and installed as a Django app."""
    return ETHOS_INSTALLED and ethos_app_installed()


def ethos_module(path):
    """Lazily import ``<ethos root>.<path>``; None when ethos is unavailable."""
    if not ethos_enabled():
        return None
    try:
        return importlib.import_module('%s.%s' % (ETHOS_ROOT, path))
    except ImportError:
        return None


def ethos_client_class():
    """The ``Ethos`` API client class, or None."""
    module = ethos_module('library.ethos')
    return getattr(module, 'Ethos', None) if module else None


def ethos_not_configured_error():
    """``EthosNotConfigured`` (raised for a campus with no Ethos credentials),
    or a never-raised stand-in when ethos is unavailable."""
    module = ethos_module('credentials')
    return getattr(module, 'EthosNotConfigured', _EthosUnavailable) if module else _EthosUnavailable


def import_sections_task():
    """ethos's ``import_sections_for_term`` django-tasks task, or None."""
    module = ethos_module('tasks')
    return getattr(module, 'import_sections_for_term', None) if module else None


def ethos_log_model():
    """The ``ethos.EthosLog`` model, or None."""
    if not ethos_enabled():
        return None
    from django.apps import apps
    try:
        return apps.get_model(ETHOS_APP_LABEL, 'EthosLog')
    except LookupError:
        return None


def requires_ethos(view):
    """Decorate a registry action so it answers with a clear alert instead of
    reaching for ethos when the app is unavailable."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not ethos_enabled():
            from django.http import JsonResponse
            return JsonResponse({'outcome': 'alert', 'status': 'error',
                                 'title': 'SIS', 'message': ETHOS_MISSING_MESSAGE})
        return view(request, *args, **kwargs)
    return wrapper


def ethos_action_permission(user):
    """``permission=`` callable for registry actions: hides SIS actions that
    need ethos when the app is unavailable."""
    return ethos_enabled()
