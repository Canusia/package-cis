"""Campus scoping for high schools.

A high school belongs to a campus through ``HighSchoolCampus``. These helpers
answer "which schools does this campus serve" for list pages, pickers and the
SIS importer. ``campus=None`` means ``current_campus_or_none()``.

In multi-campus mode with no campus they fail closed (nothing), never open.
"""
from django.db.models import Q

from cis.campus_context import current_campus_or_none, is_multi_campus
from cis.models.highschool import HighSchool, HighSchoolCampus


def _campus(campus):
    return campus if campus is not None else current_campus_or_none()


def campus_highschools(campus=None):
    """Schools with an Active link to the campus."""
    campus = _campus(campus)
    if campus is None:
        return HighSchool.objects.none()
    return HighSchool.objects.filter(
        campus_links__campus=campus, campus_links__status='Active').distinct()


def scope_highschools(qs, campus=None, user=None):
    """Narrow ``qs`` to schools linked (any status) to the campus."""
    if user is not None and getattr(user, 'is_superuser', False):
        return qs
    campus = _campus(campus)
    if campus is None:
        return qs.none()
    return qs.filter(campus_links__campus=campus).distinct()


def picker_queryset(campus=None, keep=None):
    """Active schools for the campus plus ``keep`` (instance, pk or None).

    ``keep`` retains a form's current value when it is unlinked or inactive.
    """
    keep_pk = getattr(keep, 'pk', keep)
    pks = campus_highschools(campus).values('pk')
    cond = Q(pk__in=pks)
    if keep_pk is not None:
        cond |= Q(pk=keep_pk)
    return HighSchool.objects.filter(cond).distinct().order_by('name')


def highschool_for_building_code(code, campus=None):
    """The school the campus's building ``code`` names, or None.

    Matches a link of any status. Only a single-campus deployment falls back
    to the legacy ``sau`` / ``code`` columns.
    """
    if not code:
        return None
    campus = _campus(campus)
    if campus is not None:
        link = (HighSchoolCampus.objects
                .filter(campus=campus, building_code=code)
                .select_related('highschool').first())
        if link:
            return link.highschool
    if is_multi_campus():
        return None
    return (HighSchool.objects.filter(Q(sau=code) | Q(code=code))
            .order_by('name').first())
