"""Campus scoping for high schools.

A high school belongs to a campus through ``HighSchoolCampus``. These helpers
answer "which schools does this campus serve" for list pages, pickers and the
SIS importer. ``campus=None`` means ``current_campus_or_none()``.

In multi-campus mode with no campus they fail closed (nothing), never open.

A single-campus deployment with no prefixed campus at all (so no campus
resolves and no links can exist) keeps its pre-link behaviour: pickers offer
the schools whose own status is Active, and list scoping is a no-op.
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
        if not is_multi_campus():
            # Single-campus with no prefixed campus: unchanged legacy picker.
            return HighSchool.objects.filter(status__iexact='active')
        return HighSchool.objects.none()
    return HighSchool.objects.filter(
        campus_links__campus=campus, campus_links__status='Active').distinct()


def scope_highschools(qs, campus=None, user=None):
    """Narrow ``qs`` to schools linked (any status) to the campus."""
    if user is not None and getattr(user, 'is_superuser', False):
        return qs
    campus = _campus(campus)
    if campus is None:
        # Single-campus with no prefixed campus: unchanged; multi-campus: none.
        return qs if not is_multi_campus() else qs.none()
    return qs.filter(campus_links__campus=campus).distinct()


def picker_queryset(campus=None, keep=None):
    """Active schools for the campus plus ``keep`` (instance, pk or None).

    ``keep`` retains a form's current value when it is unlinked or inactive.
    """
    keep_pk = getattr(keep, 'pk', keep)
    if keep_pk == '':
        keep_pk = None  # a blank form value / setting
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


def can_manage_link(user, campus):
    """May ``user`` add, edit, remove or set the status of a link on ``campus``?

    Superusers always. Single-campus: any CE staff member (there is one
    campus, and staff need no process_campuses rows for it). Multi-campus:
    staff on that campus (``can_process_campus``).
    """
    from cis.campus_gate import can_process_campus, user_has_cis_role
    if getattr(user, 'is_superuser', False):
        return True
    if not is_multi_campus():
        return user_has_cis_role(user)
    return campus is not None and can_process_campus(user, campus)


def manageable_campuses(user):
    """Prefixed campuses on which ``user`` may manage links (see can_manage_link)."""
    from cis.campus_gate import (
        _prefixed_campuses, get_process_campus_ids, user_has_cis_role)
    campuses = _prefixed_campuses()
    if getattr(user, 'is_superuser', False):
        return campuses
    if not is_multi_campus():
        return campuses if user_has_cis_role(user) else campuses.none()
    return campuses.filter(id__in=get_process_campus_ids(user))
