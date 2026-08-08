"""Academic-calendar constants shared across the platform.

Kept in its own module, deliberately free of model and settings imports, so
that form widgets and other low-level code can import it without dragging in
``cis.models``.
"""
import datetime

#: Month (1-12) in which the academic year rolls over — the first month in
#: which a student is considered to have advanced a grade, and in which the
#: graduating class is treated as having finished.
#:
#: This value was hand-written in seven places across the platform and the
#: copies did not agree (June here and in several tenants, July in csn, May in
#: ``form_fields``'s graduation widget). Disagreement is not cosmetic: a widget
#: offering a year range derived from one rollover, feeding a grade derivation
#: using another, opens a window where the offered years map to no grade level
#: at all and ``grade_level`` silently lands blank.
#:
#: Import this rather than re-typing a month test.
GRADE_LEVEL_ROLLOVER_MONTH = 6

#: How many graduating classes are in high school at once (FR/SO/JR/SR).
HIGH_SCHOOL_YEARS = 4


def graduation_years(today=None):
    """The graduating classes currently in high school, soonest first.

    Every year returned maps to exactly one grade in
    ``Student.get_grade_level``, which is the property that matters: a
    graduation year outside this window derives to no grade at all, and a blank
    ``grade_level`` makes a student's registration invisible to high school
    admins rather than invalid. Anything offering a graduation year to a
    student — date widgets especially — should source the range here rather
    than deriving its own, since a range and a derivation that disagree by even
    one month reopen exactly that gap.
    """
    today = today or datetime.date.today()
    first = today.year + 1 if today.month >= GRADE_LEVEL_ROLLOVER_MONTH else today.year
    return list(range(first, first + HIGH_SCHOOL_YEARS))
