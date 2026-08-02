"""
Pluggable, decorator-registered page messages.

A provider is a function ``fn(request) -> PageMessage | list[PageMessage] | None``
registered against an ``(app, page)`` scope with ``@page_message(app, page)``.
A view calls ``get_page_messages(app, page, request)`` and hands the result to
the ``cis/page_messages.html`` partial. Providers live in each app's
``page_messages.py`` module, auto-discovered at startup (see cis/apps.py).
"""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_ICONS = {
    'danger': 'fa fa-exclamation-triangle',
    'warning': 'fa fa-exclamation-triangle',
    'success': 'fa fa-check-circle',
    'info': 'fa fa-info-circle',
}


@dataclass
class PageMessage:
    """One alert to render on a page. ``text`` may contain HTML (rendered |safe)."""
    text: str
    level: str = 'danger'          # danger | warning | success | info
    icon: str = ''                 # FontAwesome classes; defaults from level
    tile_id: str = ''              # optional dashboard tile element id to highlight
    url: str = ''                  # optional link target

    def __post_init__(self):
        if not self.icon:
            self.icon = DEFAULT_ICONS.get(self.level, DEFAULT_ICONS['info'])


# (app, page) -> [provider, ...]
_REGISTRY = {}


def page_message(app, page):
    """Register ``fn(request)`` as a provider for the ``(app, page)`` scope."""
    def decorator(fn):
        _REGISTRY.setdefault((app, page), []).append(fn)
        return fn
    return decorator


def get_page_messages(app, page, request):
    """Run every provider registered for ``(app, page)``; return flat PageMessage list.

    Providers are isolated: one that raises is logged and skipped. A provider may
    return a PageMessage, a list/tuple of them, or None.
    """
    out = []
    for fn in _REGISTRY.get((app, page), []):
        try:
            result = fn(request)
        except Exception:
            log.exception('page_message provider %r failed', getattr(fn, '__name__', fn))
            continue
        if result is None:
            continue
        if isinstance(result, PageMessage):
            out.append(result)
        elif isinstance(result, (list, tuple)):
            out.extend(m for m in result if isinstance(m, PageMessage))
    return out
