"""Which campus the running code is serving (MC-01, package-cis #25).

Signals, management commands and cron jobs run outside a request, so the
thread-local ``current_request()`` (cis/middleware.py) cannot tell them which
campus they serve. This module can: ``campus_context(campus)`` sets the campus
for a block of code, and ``current_campus()`` reads it anywhere inside it.

Backed by a ``contextvars.ContextVar``, so each thread and each async task has
its own value, and nested contexts restore the outer campus on exit, including
when the block raises.

Single-campus deployments (every tenant today) need no context at all:
``current_campus()`` falls back to the deployment's only campus, so existing
behaviour is unchanged. Only in multi-campus mode does a missing context raise
``NoCampusContext``, because guessing a campus there would leak one college's
data or settings into the other's.

Multi-campus mode is on only when ``settings.MULTI_CAMPUS`` is True. It is not
derived from the data: a second campus carrying ``CAMPUS_CODE_PREFIX`` is
common (tests build them routinely, and a tenant can add one by hand), and
deriving the mode from it would switch a running deployment into host-based
routing -- and 400 every request -- the moment one was saved.

A single-campus deployment's campus is its first prefixed campus by name
(``deployment_campus()``), the same rule the settings migration uses.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings

_current = ContextVar('cis_current_campus', default=None)


class NoCampusContext(RuntimeError):
    """Raised by current_campus() in multi-campus mode when no campus is set."""


def _prefixed_campuses():
    from cis.campus_gate import _prefixed_campuses as prefixed
    return prefixed()


def is_multi_campus():
    return bool(getattr(settings, 'MULTI_CAMPUS', False))


def deployment_campus():
    """A single-campus deployment's campus: its first prefixed campus by name."""
    return _prefixed_campuses().order_by('name').first()


def current_campus_or_none():
    """The active campus; the only campus when single-campus; otherwise None."""
    campus = _current.get()
    if campus is not None:
        return campus
    if is_multi_campus():
        return None
    return deployment_campus()


def current_campus():
    """The campus the running code is serving.

    Raises NoCampusContext in multi-campus mode when no campus_context() is
    active. A single-campus deployment gets its only campus (None if it has
    none at all).
    """
    campus = _current.get()
    if campus is not None:
        return campus
    if is_multi_campus():
        raise NoCampusContext(
            'No campus is set. Wrap this code in cis.campus_context.campus_context(campus).')
    return deployment_campus()


@contextmanager
def campus_context(campus):
    """Serve ``campus`` for the duration of the block, then restore the previous one."""
    token = _current.set(campus)
    try:
        yield campus
    finally:
        _current.reset(token)


def campus_url(campus, path=''):
    """Absolute https URL for ``path`` on ``campus``'s host (MC-10, #34).

    The domain is campus.site.domain. Without one -- a single-campus
    deployment, where Campus.site is usually null -- it is the current Site,
    exactly as cis has always built links. In multi-campus mode a campus with
    no Site raises rather than borrowing another college's host for a link
    that goes out in an email.
    """
    from django.contrib.sites.models import Site
    from django.core.exceptions import ImproperlyConfigured

    if campus is not None and getattr(campus, 'site_id', None):
        domain = campus.site.domain
    elif is_multi_campus():
        raise ImproperlyConfigured(
            f'Campus {campus} has no Site; set Campus.site to build its links.')
    else:
        domain = Site.objects.get_current().domain

    if not domain.startswith(('http://', 'https://')):
        domain = f'https://{domain}'
    return domain.rstrip('/') + path


def active_campus():
    """The campus set by an enclosing campus_context(), or None -- no fallback."""
    return _current.get()


def scope_to_current_campus(queryset, path, distinct=False):
    """Narrow ``queryset`` to the current campus in multi-campus mode (MC-11, #35).

    ``path`` is the lookup from the model to its Campus (``course__campus``,
    ``student__studentregistration__class_section__course__campus``). Pass
    ``distinct=True`` when the path crosses a to-many relation. Single-campus
    mode returns the queryset unchanged; multi-campus mode with no campus
    raises NoCampusContext rather than processing every college's records.
    """
    if not is_multi_campus():
        return queryset
    scoped = queryset.filter(**{path: current_campus()})
    return scoped.distinct() if distinct else scoped
