"""Instructor/faculty portal page text, read from whichever app owns it.

The text is moving into package-instructor_portal and package-faculty (#81,
#82). Same source order as the portal_text helpers in grades, drop_wd,
instructor_app and docrepo: the package's nested layout, its installed layout,
then cis's deprecated copy.
"""
import importlib
import importlib.util
import warnings

from .apps import PORTAL_TEXT_OWNERS

_CLASSES = {
    'faculty_portal': 'faculty_portal_text',
    'instructor_portal': 'instructor_portal',
}


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def portal_text(name):
    """Stored text for ``name`` ('faculty_portal' / 'instructor_portal'), or {}."""
    for module in PORTAL_TEXT_OWNERS[name]:
        if _has_module(module):
            value = getattr(importlib.import_module(module), _CLASSES[name]).from_db()
            return value if isinstance(value, dict) else {}
    with warnings.catch_warnings():  # cis's own fallback, not a caller to warn
        warnings.simplefilter('ignore', DeprecationWarning)
        module = importlib.import_module(f'cis.settings.{name}')
    value = getattr(module, name).from_db()
    return value if isinstance(value, dict) else {}
