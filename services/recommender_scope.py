"""Which HS admins recommend for which students: recommender buckets.

A position holding ``can_manage_student_recommendation`` covers students of
its high school. With no recommender buckets it covers all of them (the
behaviour before buckets, and the fallback for students no bucket covers);
with buckets, only students whose last-name initial falls in one of them.

Which school recommends for a registration is the Counselor Rec. Form
setting's ``recommending_school``: the student's high school (default), the
class's host high school (the student's when the section has none), or both.
Buckets apply at whichever school recommends; the student's last name picks
the letter.

Every surface that decides "may this admin recommend for this registration"
goes through this module — the student page, the pending list and count, and
the counselor digest — so they cannot disagree about who sees whom.

The initial is the first character of ``user.last_name``, leading spaces
trimmed, accents folded (Á→A, Ñ→N, Ø→O), upper-cased. Folding uses one table
(``FOLD_FROM``/``FOLD_TO``) on both the Python and the SQL side — SQL applies
it with TRANSLATE, so no ``unaccent`` extension is needed — which keeps the two
in step. Whatever is still outside A–Z (digits, other scripts, blank) matches
no bucket, so only unranged positions cover it. Buckets are matched with
``initial IN (letters)``, never ``BETWEEN``: a range comparison follows the
database collation, while equality does not.
"""
import logging
import unicodedata
from collections import OrderedDict

from django.db.models import CharField, F, Func, Prefetch, Q, Value
from django.db.models.functions import Left, Trim, Upper

from cis.models.highschool_administrator import (
    ANY_CAMPUS, HSAdminPerm, HSAdministrator, HSAdministratorPosition)
from cis.models.recommender_bucket import LETTERS, RecommenderBucket
from cis.settings.counselor_recommendation import (
    BOTH_SCHOOLS, CLASS_SCHOOL, STUDENT_SCHOOL)

logger = logging.getLogger(__name__)

INITIAL_ANNOTATION = '_recommender_initial'


def _fold_table():
    """Latin letters whose decomposition starts with an ASCII letter, mapped to
    it, plus the few that do not decompose (Ø, Ł, Đ, Æ, Œ, ß...)."""
    src, dst = [], []
    for code in range(0xC0, 0x250):
        ch = chr(code)
        base = unicodedata.normalize('NFKD', ch)[:1]
        if base.isascii() and base.isalpha() and base != ch:
            src.append(ch)
            dst.append(base)
    for ch, base in (('Ø', 'O'), ('ø', 'o'), ('Ł', 'L'), ('ł', 'l'), ('Đ', 'D'),
                     ('đ', 'd'), ('Æ', 'A'), ('æ', 'a'), ('Œ', 'O'), ('œ', 'o'),
                     ('ß', 's'), ('Þ', 'T'), ('þ', 't'), ('Ð', 'D'), ('ð', 'd'),
                     ('Ħ', 'H'), ('ħ', 'h'), ('ı', 'i')):
        if ch not in src:
            src.append(ch)
            dst.append(base)
    return ''.join(src), ''.join(dst)


FOLD_FROM, FOLD_TO = _fold_table()
_FOLD = str.maketrans(FOLD_FROM, FOLD_TO)


def initial_of(last_name):
    """'A'..'Z', or None when the name does not start with a (folded) letter."""
    first = (last_name or '').lstrip(' ')[:1].translate(_FOLD)
    if not first.isascii():
        return None
    first = first.upper()
    return first if first in LETTERS else None


def student_initial(student):
    return initial_of(student.user.last_name if student and student.user_id else None)


def student_initial_sql(prefix=''):
    """SQL twin of student_initial: first character, spaces trimmed, accents
    folded, upper. Compare it only by equality to single A–Z letters (see
    module docstring)."""
    first = Left(Trim(F(f'{prefix}user__last_name')), 1)
    folded = Func(first, Value(FOLD_FROM), Value(FOLD_TO),
                  function='TRANSLATE', output_field=CharField())
    return Upper(folded)


def recommending_school_mode(config=None):
    """The setting's ``recommending_school``: STUDENT_SCHOOL, CLASS_SCHOOL or
    BOTH_SCHOOLS. Missing or unknown values mean STUDENT_SCHOOL.

    `config` is an already-read ``counselor_recommendation.from_db()``, to save
    the query. The setting is per campus, so the campus serving the request
    decides (as for ``require_grade_level_match``); with no campus in context
    on a multi-campus site it is STUDENT_SCHOOL, the behaviour before it
    existed."""
    if config is None:
        from cis.campus_context import NoCampusContext
        from cis.settings.counselor_recommendation import counselor_recommendation
        try:
            config = counselor_recommendation.from_db()
        except NoCampusContext:
            config = {}
    mode = (config or {}).get('recommending_school')
    return mode if mode in (CLASS_SCHOOL, BOTH_SCHOOLS) else STUDENT_SCHOOL


def recommending_school_q(highschool_ids, prefix='', mode=None):
    """Q for registrations (reached through `prefix`, '' for a
    StudentRegistration queryset) whose recommending school is one of
    `highschool_ids`."""
    mode = mode or recommending_school_mode()
    ids = list(highschool_ids)
    student = Q(**{f'{prefix}student__highschool_id__in': ids})
    if mode == STUDENT_SCHOOL:
        return student
    host = Q(**{f'{prefix}class_section__highschool_id__in': ids})
    if mode == CLASS_SCHOOL:
        return host | (Q(**{f'{prefix}class_section__highschool__isnull': True}) & student)
    return host | student


def recommending_school_ids_of(registrations, mode=None):
    """Ids of every recommending school of `registrations`."""
    mode = mode or recommending_school_mode()
    ids = set()
    if mode in (STUDENT_SCHOOL, BOTH_SCHOOLS):
        ids |= set(registrations.values_list('student__highschool_id', flat=True).distinct())
    if mode in (CLASS_SCHOOL, BOTH_SCHOOLS):
        ids |= set(registrations.values_list(
            'class_section__highschool_id', flat=True).distinct())
    if mode == CLASS_SCHOOL:
        ids |= set(registrations.filter(class_section__highschool__isnull=True).values_list(
            'student__highschool_id', flat=True).distinct())
    ids.discard(None)
    return ids


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


def scope_registrations(qs, hsadmin, campus=None, prefix=''):
    """Narrow `qs` (StudentRegistrations, or rows reaching one through
    `prefix`) to the registrations `hsadmin` may recommend for: one of their
    positions is at a recommending school of the registration and covers the
    student's initial.

    Apply before any DISTINCT ON.
    """
    if hsadmin is None:
        return qs.none()
    positions = list(recommender_positions(campus, hsadmin=hsadmin))
    if not positions:
        return qs.none()

    mode = recommending_school_mode()
    q = Q(pk__in=[])
    for position in positions:
        school = recommending_school_q([position.highschool_id], prefix, mode)
        buckets = list(position.recommender_buckets.all())
        if not buckets:
            q |= school
            continue
        letters = sorted({c for b in buckets for c in b.letters()})
        q |= school & Q(**{f'{INITIAL_ANNOTATION}__in': letters})
    return qs.annotate(
        **{INITIAL_ANNOTATION: student_initial_sql(f'{prefix}student__')}).filter(q)


def recommenders_for_registration(registration, campus=None):
    """HSAdministrators who may recommend for `registration`."""
    from cis.models.section import StudentRegistration
    school_ids = recommending_school_ids_of(
        StudentRegistration.objects.filter(pk=registration.pk))
    initial = student_initial(registration.student)
    ids = {p.hsadmin_id for p in recommender_positions(campus, highschool_ids=school_ids)
           if position_covers(p, initial)}
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


def recommender_groups(registrations, campus=None):
    """Counselor digest groups for `registrations` (applied, awaiting a
    recommendation): by recommending school, then by the counselors covering
    each student (split_by_recommenders). One row per student per school.
    With both schools recommending, a registration appears under each."""
    from cis.models.highschool import HighSchool

    mode = recommending_school_mode()
    groups = []
    for highschool in HighSchool.objects.filter(
            id__in=recommending_school_ids_of(registrations, mode)).order_by('name'):
        groups.extend(split_by_recommenders(
            highschool,
            registrations.filter(
                recommending_school_q([highschool.id], mode=mode)).distinct('student'),
            campus=campus))
    return groups


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
    ``non_az_students`` (students awaiting a recommendation whose initial
    matches no bucket).
    """
    from cis.models.section import StudentRegistration

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

    from cis.utils import registration_terms
    non_az = StudentRegistration.objects.awaiting_recommendation(
        terms=registration_terms() or []).filter(
        recommending_school_q([highschool.id])).annotate(
        **{INITIAL_ANNOTATION: student_initial_sql('student__')}).exclude(
        **{f'{INITIAL_ANNOTATION}__in': LETTERS}).values('student').distinct().count()

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
