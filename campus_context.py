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

Multi-campus mode is ``settings.MULTI_CAMPUS`` when that is set, and otherwise
derived from the data: more than one campus whose code carries
``CAMPUS_CODE_PREFIX`` (the same "prefixed campuses" campus_gate scopes to).
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
    explicit = getattr(settings, 'MULTI_CAMPUS', None)
    if explicit is not None:
        return bool(explicit)
    return _prefixed_campuses().count() > 1


def _default_campus():
    """The deployment's campus when it runs as a single campus, else None."""
    return _prefixed_campuses().order_by('name').first()


def current_campus_or_none():
    """The active campus; the only campus when single-campus; otherwise None."""
    campus = _current.get()
    if campus is not None:
        return campus
    if is_multi_campus():
        return None
    return _default_campus()


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
    return _default_campus()


@contextmanager
def campus_context(campus):
    """Serve ``campus`` for the duration of the block, then restore the previous one."""
    token = _current.set(campus)
    try:
        yield campus
    finally:
        _current.reset(token)
