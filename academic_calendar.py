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
    return list(range(senior_graduation_year(today),
                      senior_graduation_year(today) + HIGH_SCHOOL_YEARS))


#: Years until graduation -> grade code. Seniors graduate this school year.
GRADE_BY_YEARS_UNTIL_GRADUATION = {0: 'SR', 1: 'JR', 2: 'SO', 3: 'FR'}

#: Returned when graduation is already behind the student.
GRADUATED = 'GRAD'

#: Returned when the graduation input cannot be read at all.
UNKNOWN = '--'


def senior_graduation_year(as_of=None):
    """The calendar year in which the *current* senior class graduates.

    Deriving this first is what fixes the long-standing off-by-one. The old
    implementation subtracted calendar years and then patched the result with a
    month test, and that decrement was doing two unrelated jobs at once: rolling
    the academic year forward (true of every student, every year) and deciding
    whether this particular student had already finished (only ever about the
    graduating class). Its guard existed for the second job but could only act
    by switching off the first, and its condition — "is the graduation date in
    the future" — is true of every enrolled student. So it suppressed the
    rollover for the entire student body in order to protect the seniors.

    Anchoring on the senior class year leaves no decrement to skip, so there is
    nothing for a guard to break.
    """
    as_of = as_of or datetime.date.today()
    return as_of.year + 1 if as_of.month >= GRADE_LEVEL_ROLLOVER_MONTH else as_of.year


def grade_level_from_graduation(graduation_year=None, graduation_date=None,
                                as_of=None):
    """Grade for the school year containing ``as_of``.

    Accepts either input. A full date wins where it adds information, because
    only a date can distinguish "graduates in ten days" from "graduated last
    month".

    Returns a grade code, ``GRADUATED`` when graduation is behind them,
    ``UNKNOWN`` when the input cannot be parsed, or ``None`` when the year is
    readable but outside high school (more than ``HIGH_SCHOOL_YEARS`` away).
    Those last three are sentinels, not grades — callers must not persist them.
    """
    as_of = as_of or datetime.date.today()

    if graduation_date is not None:
        if hasattr(graduation_date, 'date'):      # datetime -> date
            graduation_date = graduation_date.date()
        graduation_year = graduation_date.year

    if graduation_year is None or graduation_year == '':
        return UNKNOWN
    try:
        graduation_year = int(graduation_year)
    except (TypeError, ValueError):
        return UNKNOWN

    years_until = graduation_year - senior_graduation_year(as_of)

    # Only a date can tell us they have not actually finished yet. Clamping at
    # zero can only lift a value the arithmetic already calls graduated, so —
    # unlike the guard it replaces — it cannot reach a freshman.
    if graduation_date is not None and graduation_date >= as_of:
        years_until = max(years_until, 0)

    if years_until < 0:
        return GRADUATED
    return GRADE_BY_YEARS_UNTIL_GRADUATION.get(years_until)
