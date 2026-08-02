"""The one and only place ``cis`` is allowed to reference the ``grades`` app.

WHY THIS MODULE EXISTS
----------------------
``cis`` ships as the ``myce_cis`` package to every tenant. ``grades``
(``myce_grades``) is optional: a tenant may deploy MyCE with no grades module at
all. Historically ``cis`` imported ``grades`` directly in ~10 places — three at
module level — which made a supposedly optional app a hard requirement and made
"runs without grades" untestable.

The dependency now runs one way only: ``grades`` imports ``cis``; ``cis`` does
not import ``grades``. The handful of genuine cis-side readers of a grade fact
(the CE sections list stats, the cis class export,
``StudentRegistration.submitted_grade``, the ``cis.utils`` window delegations,
``Student.get_transcript``) go through the accessors below.

Rules for future work:

* **Do not** add ``from grades…`` / ``import grades`` anywhere else in ``cis``.
  ``grep -rn "from grades\\|import grades" cis/`` must match this file only.
* Every accessor returns a safe, typed default when grades is absent — callers
  never need their own guard.
* Imports of ``grades.services.*`` happen lazily *inside* the function bodies so
  that neither app-loading order nor the app's absence can break ``cis`` import.
* Keep this module dependency-free: no Django model imports at module level.

Grades may be installed either flat (``grades``, pip) or nested
(``grades.grades``, editable submodule); both are detected, once, at import.
"""

import importlib
import importlib.util

__all__ = [
    'HAS_GRADES',
    'grade_scale',
    'grade_terms',
    'is_submit_grades_open',
    'can_view_grades',
    'page_header_for_instructor',
    'submitted_grade',
    'render_transcript',
    'students_for_grades',
]


def _detect_grades_root():
    """Return the importable root package name for grades, or None if absent.

    Resolved once at module import; the editable-submodule layout
    (``grades.grades``) wins over the flat pip layout (``grades``), matching the
    house ``find_spec`` idiom used elsewhere in ``cis``.
    """
    for name in ('grades.grades', 'grades'):
        try:
            if importlib.util.find_spec(name) is not None:
                return name
        except (ImportError, AttributeError, ValueError):
            continue
    return None


_GRADES_ROOT = _detect_grades_root()

#: True when a grades app is installed in either layout.
HAS_GRADES = _GRADES_ROOT is not None


def _service(module):
    """Lazily import ``grades.services.<module>``; None when grades is absent."""
    if not HAS_GRADES:
        return None
    try:
        return importlib.import_module('%s.services.%s' % (_GRADES_ROOT, module))
    except ImportError:
        return None


def grade_scale():
    """Configured grade values, e.g. ``['A', 'B', …]``. ``[]`` when absent."""
    window = _service('window')
    if window is None:
        return []
    return window.grade_scale()


def grade_terms():
    """Terms currently in scope for grading. ``[]`` when absent."""
    window = _service('window')
    if window is None:
        return []
    return window.grade_terms()


def is_submit_grades_open():
    """Whether the grade-submission window is open. ``False`` when absent."""
    window = _service('window')
    if window is None:
        return False
    return window.is_submit_grades_open()


def can_view_grades():
    """Whether grades may be viewed right now. ``False`` when absent."""
    window = _service('window')
    if window is None:
        return False
    return window.can_view_grades()


def page_header_for_instructor():
    """Instructor-facing grades page header text. ``''`` when absent."""
    window = _service('window')
    if window is None:
        return ''
    return window.page_header_for_instructor()


def submitted_grade(registration):
    """Display grade for a ``StudentRegistration``. ``'-'`` when absent."""
    window = _service('window')
    if window is None:
        return '-'
    return window.submitted_grade(registration)


def render_transcript(student, request=None):
    """Render a student's transcript. ``None`` when absent."""
    transcript = _service('transcript')
    if transcript is None:
        return None
    return transcript.render_transcript(student, request=request)


def students_for_grades(section):
    """Roster rows gradeable for ``section``. Empty list when absent."""
    roster = _service('roster')
    if roster is None:
        return []
    return roster.students_for_grades(section)
