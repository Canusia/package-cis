"""Which HS admins recommend for which students: recommender buckets.

A position holding ``can_manage_student_recommendation`` covers students of
its high school. With no recommender buckets it covers all of them (the
behaviour before buckets, and the fallback for students no bucket covers);
with buckets, only students whose last-name initial falls in one of them.

Every surface that decides "may this admin recommend for this student" goes
through this module — the student page, the pending list and count, and the
counselor digest — so they cannot disagree about who sees whom.

The initial is the first character of ``user.last_name``, leading spaces
trimmed, upper-cased. Anything outside A–Z (accents, digits, blank) matches no
bucket, so only unranged positions cover it. Buckets are matched with
``initial IN (letters)``, never ``BETWEEN``: a range comparison follows the
database collation, under which 'Á' sorts inside A–F, while equality does not.
"""
import logging
from collections import OrderedDict

from django.db.models import F, Prefetch, Q
from django.db.models.functions import Left, Trim, Upper

from cis.models.highschool_administrator import (
    ANY_CAMPUS, HSAdminPerm, HSAdministrator, HSAdministratorPosition)
from cis.models.recommender_bucket import LETTERS, RecommenderBucket

logger = logging.getLogger(__name__)

INITIAL_ANNOTATION = '_recommender_initial'


def initial_of(last_name):
    """'A'..'Z', or None when the name does not start with one."""
    first = (last_name or '').lstrip(' ')[:1].upper()
    return first if first in LETTERS else None


def student_initial(student):
    return initial_of(student.user.last_name if student and student.user_id else None)


def student_initial_sql(prefix=''):
    """SQL twin of student_initial: first character, spaces trimmed, upper.
    Compare it only by equality to single A–Z letters (see module docstring)."""
    return Upper(Left(Trim(F(f'{prefix}user__last_name')), 1))


def recommender_positions(campus=None, highschool_ids=None, hsadmin=None):
    """Active positions holding the recommendation permission for `campus`,
    with their buckets prefetched."""
    qs = HSAdministratorPosition.objects.with_perm(
        HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION, campus)
    if highschool_ids is not None:
        qs = qs.filter(highschool_id__in=list(highschool_ids))
    if hsadmin is not None:
        qs = qs.filter(hsadmin=hsadmin)
    return qs.prefetch_related(
        Prefetch('recommender_buckets', queryset=RecommenderBucket.objects.order_by(
            'start_letter', 'end_letter')))


def position_covers(position, initial):
    buckets = list(position.recommender_buckets.all())
    if not buckets:
        return True
    return any(b.covers(initial) for b in buckets)


def admin_covers_student(hsadmin, student, highschool_id, campus=None):
    """True if one of `hsadmin`'s positions at `highschool_id` holds the
    permission for `campus` and covers `student`."""
    if not highschool_id:
        return False
    initial = student_initial(student)
    return any(position_covers(p, initial) for p in recommender_positions(
        campus, highschool_ids=[highschool_id], hsadmin=hsadmin))


def scope_students(qs, hsadmin, campus=None, prefix=''):
    """Narrow `qs` (Students, or rows reaching a student through `prefix`, e.g.
    'student__' for registrations) to the students `hsadmin` may recommend for.

    Filters on the student's own high school. Apply before any DISTINCT ON.
    """
    if hsadmin is None:
        return qs.none()
    positions = list(recommender_positions(campus, hsadmin=hsadmin))
    if not positions:
        return qs.none()

    q = Q(pk__in=[])
    for position in positions:
        school = Q(**{f'{prefix}highschool_id': position.highschool_id})
        buckets = list(position.recommender_buckets.all())
        if not buckets:
            q |= school
            continue
        letters = sorted({c for b in buckets for c in b.letters()})
        q |= school & Q(**{f'{INITIAL_ANNOTATION}__in': letters})
    return qs.annotate(**{INITIAL_ANNOTATION: student_initial_sql(prefix)}).filter(q)


def recommenders_for_student(student, campus=None):
    """HSAdministrators who may recommend for `student` (its own school)."""
    if not student.highschool_id:
        return HSAdministrator.objects.none()
    initial = student_initial(student)
    ids = {p.hsadmin_id for p in recommender_positions(
        campus, highschool_ids=[student.highschool_id]) if position_covers(p, initial)}
    return HSAdministrator.objects.filter(id__in=ids)


def split_by_recommenders(highschool, registrations, campus=None):
    """Counselor digest groups for one school: the school's `registrations`
    regrouped by the set of counselors who cover each student.

    Returns ``[{'highschool', 'registrations', 'recipients'}]`` — the shape of
    ``counselor_notification_groups`` — so each counselor is emailed only about
    their own students. A student nobody covers is logged and left out.
    """
    positions = list(recommender_positions(
        campus, highschool_ids=[highschool.id]).select_related('hsadmin__user'))
    groups = OrderedDict()
    for registration in registrations.select_related('student__user'):
        initial = student_initial(registration.student)
        recipients = tuple(sorted({
            p.hsadmin.user.email for p in positions
            if p.hsadmin.user.email and position_covers(p, initial)}))
        if not recipients:
            logger.info('No recommender covers student %s at %s',
                        registration.student_id, highschool.id)
            continue
        groups.setdefault(recipients, []).append(registration.pk)

    return [{
        'highschool': highschool,
        'registrations': registrations.filter(pk__in=ids),
        'recipients': list(recipients),
    } for recipients, ids in groups.items()]


def _runs(letters):
    """['A','B','C','F'] -> ['A–C', 'F']."""
    runs, start, prev = [], None, None
    for c in LETTERS + (None,):
        if c in letters:
            start = start or c
            prev = c
        elif start:
            runs.append(start if start == prev else f'{start}–{prev}')
            start = None
    return runs


def coverage(highschool):
    """What the school's buckets cover, for the coverage bar.

    Only buckets with an assigned Active, permitted position count (for any
    campus). Returns ``letters`` (one dict per A–Z with its admins and a state
    of covered / overlap / gap), ``gaps`` and ``overlaps`` as run labels,
    ``fallback`` (unranged admins, who cover the gaps), ``has_buckets`` and
    ``non_az_students`` (students whose initial matches no bucket).
    """
    from cis.models.student import Student

    positions = list(recommender_positions(
        ANY_CAMPUS, highschool_ids=[highschool.id]).select_related('hsadmin__user'))
    by_letter = {c: set() for c in LETTERS}
    fallback = OrderedDict()
    has_buckets = False
    for p in positions:
        buckets = list(p.recommender_buckets.all())
        name = str(p.hsadmin)
        if not buckets:
            fallback[p.hsadmin_id] = name
            continue
        has_buckets = True
        for b in buckets:
            for c in b.letters():
                by_letter[c].add(name)

    letters = []
    for c in LETTERS:
        admins = sorted(by_letter[c])
        state = 'gap' if not admins else ('overlap' if len(admins) > 1 else 'covered')
        letters.append({'letter': c, 'admins': admins, 'state': state})

    non_az = Student.objects.filter(highschool=highschool).annotate(
        **{INITIAL_ANNOTATION: student_initial_sql()}).exclude(
        **{f'{INITIAL_ANNOTATION}__in': LETTERS}).count()

    return {
        'letters': letters,
        'gaps': _runs({d['letter'] for d in letters if d['state'] == 'gap'}),
        'overlaps': _runs({d['letter'] for d in letters if d['state'] == 'overlap'}),
        'fallback': list(fallback.values()),
        'has_buckets': has_buckets,
        'non_az_students': non_az,
    }


def assign_buckets(position, buckets):
    """Replace `position`'s buckets. Every bucket must belong to the
    position's high school."""
    buckets = list(buckets)
    wrong = [b for b in buckets if b.highschool_id != position.highschool_id]
    if wrong:
        raise ValueError(
            'Recommender buckets belong to another high school: '
            + ', '.join(b.name for b in wrong))
    position.recommender_buckets.set(buckets)


def set_bucket_members(bucket, positions):
    """Replace which positions belong to `bucket` (same-school check)."""
    positions = list(positions)
    wrong = [p for p in positions if p.highschool_id != bucket.highschool_id]
    if wrong:
        raise ValueError('Positions belong to another high school.')
    bucket.positions.set(positions)
