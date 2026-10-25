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
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.signals import request_finished, request_started
from django.db.models.signals import post_delete, post_save

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


def _mode_of(config):
    mode = (config or {}).get('recommending_school')
    return mode if mode in (CLASS_SCHOOL, BOTH_SCHOOLS) else STUDENT_SCHOOL


def recommending_school_mode(config=None):
    """The serving campus's ``recommending_school``: STUDENT_SCHOOL,
    CLASS_SCHOOL or BOTH_SCHOOLS. Missing or unknown values mean
    STUDENT_SCHOOL.

    For decisions about one page (the HS admin student page, served on one
    campus). Querysets that can span campuses use :func:`school_rule`.
    `config` is an already-read ``counselor_recommendation.from_db()``. With no
    campus in context on a multi-campus site it is STUDENT_SCHOOL, the
    behaviour before the setting existed."""
    if config is None:
        from cis.campus_context import NoCampusContext
        from cis.settings.counselor_recommendation import counselor_recommendation
        try:
            config = counselor_recommendation.from_db()
        except NoCampusContext:
            config = {}
    return _mode_of(config)


# school_rule() for the current request. Per-row checks (has_recommendation
# in a DataTables feed) ask for it once per row; reading the setting each time
# was a query per row. None outside a request: no caching there.
_rule_cache = ContextVar('cis_recommending_school_rule', default=None)


def _start_request_cache(**kwargs):
    _rule_cache.set({})


def _end_request_cache(**kwargs):
    _rule_cache.set(None)


def _setting_changed(sender, instance, **kwargs):
    from cis.settings.counselor_recommendation import counselor_recommendation
    cache = _rule_cache.get()
    if cache and instance.key == counselor_recommendation.key:
        cache.clear()


@contextmanager
def cached_school_rule():
    """Read school_rule() once inside the block, as a request does — for
    jobs and tests that run per-row checks outside a request."""
    token = _rule_cache.set({})
    try:
        yield
    finally:
        _rule_cache.reset(token)


request_started.connect(_start_request_cache, dispatch_uid='cis_recommending_school_rule_start')
request_finished.connect(_end_request_cache, dispatch_uid='cis_recommending_school_rule_end')
post_save.connect(_setting_changed, sender='cis.Setting',
                  dispatch_uid='cis_recommending_school_rule_saved')
post_delete.connect(_setting_changed, sender='cis.Setting',
                    dispatch_uid='cis_recommending_school_rule_deleted')


def school_rule(config=None):
    cache = _rule_cache.get()
    if config is not None or cache is None:
        return _read_school_rule(config)
    if 'rule' not in cache:
        cache['rule'] = _read_school_rule()
    return cache['rule']


def _read_school_rule(config=None):
    """The recommending-school rule for querysets: a mode string on a
    single-campus site; on a multi-campus site ``{mode: [campus ids]}`` from
    every campus's own setting, since the setting is per campus and a
    registration follows its course's campus. One query either way, none on
    a single-campus site given an already-read `config`."""
    from cis.campus_context import is_multi_campus
    if not is_multi_campus():
        return recommending_school_mode(config)
    from cis.models.settings import Setting
    from cis.settings.counselor_recommendation import counselor_recommendation
    rule = {}
    # Positional Q: keyword lookups of a campus-scoped key are narrowed to the
    # current campus; this needs every campus's row.
    for campus_id, value in Setting.objects.filter(
            Q(key=counselor_recommendation.key)).values_list('campus_id', 'value'):
        if campus_id:
            rule.setdefault(_mode_of(value), []).append(campus_id)
    return rule


def is_student_rule(rule):
    """True when every campus recommends from the student's school."""
    if isinstance(rule, str):
        return rule == STUDENT_SCHOOL
    return not (set(rule) - {STUDENT_SCHOOL})


def _school_q(ids, prefix, mode):
    student = Q(**{f'{prefix}student__highschool_id__in': ids})
    if mode == STUDENT_SCHOOL:
        return student
    host = Q(**{f'{prefix}class_section__highschool_id__in': ids})
    if mode == CLASS_SCHOOL:
        return host | (Q(**{f'{prefix}class_section__highschool__isnull': True}) & student)
    return host | student


def recommending_school_q(highschool_ids, prefix='', mode=None):
    """Q for registrations (reached through `prefix`, '' for a
    StudentRegistration queryset) whose recommending school is one of
    `highschool_ids`. `mode` is a mode or a :func:`school_rule` (read when
    omitted)."""
    rule = school_rule() if mode is None else mode
    ids = list(highschool_ids)
    if isinstance(rule, str):
        return _school_q(ids, prefix, rule)
    campus = f'{prefix}class_section__course__campus_id__in'
    others = [c for m, campuses in rule.items() if m != STUDENT_SCHOOL for c in campuses]
    # Campuses without their own row (and courses with no campus) use the
    # student's school.
    q = ~Q(**{campus: others}) & _school_q(ids, prefix, STUDENT_SCHOOL)
    for m, campuses in rule.items():
        if m != STUDENT_SCHOOL:
            q |= Q(**{campus: campuses}) & _school_q(ids, prefix, m)
    return q


def _school_ids(registrations, mode):
    ids = set()
    if mode in (STUDENT_SCHOOL, BOTH_SCHOOLS):
        ids |= set(registrations.values_list('student__highschool_id', flat=True).distinct())
    if mode in (CLASS_SCHOOL, BOTH_SCHOOLS):
        ids |= set(registrations.values_list(
            'class_section__highschool_id', flat=True).distinct())
    if mode == CLASS_SCHOOL:
        ids |= set(registrations.filter(class_section__highschool__isnull=True).values_list(
            'student__highschool_id', flat=True).distinct())
    return ids


def recommending_school_ids_of(registrations, mode=None):
    """Ids of every recommending school of `registrations` (`mode` as for
    :func:`recommending_school_q`)."""
    rule = school_rule() if mode is None else mode
    if isinstance(rule, str):
        ids = _school_ids(registrations, rule)
    else:
        others = [c for m, campuses in rule.items() if m != STUDENT_SCHOOL for c in campuses]
        ids = _school_ids(registrations.exclude(
            class_section__course__campus_id__in=others), STUDENT_SCHOOL)
        for m, campuses in rule.items():
            if m != STUDENT_SCHOOL:
                ids |= _school_ids(registrations.filter(
                    class_section__course__campus_id__in=campuses), m)
    ids.discard(None)
    return ids


def covering_outer_q(mode):
    """Q on StudentRecommendation, for a subquery correlated to a
    registration (``OuterRef``): the record covers it under `mode` — the SQL
    twin of ``StudentRecommendation.covering``. A row with no school is the
    student's own school's."""
    from django.db.models import OuterRef
    from django.db.models.lookups import Exact, IsNull
    if mode == STUDENT_SCHOOL:
        return Q()
    host, own = OuterRef('class_section__highschool'), OuterRef('student__highschool')
    if mode == CLASS_SCHOOL:
        own_school_recommends = Q(IsNull(host, True)) | Q(Exact(host, own))
    else:
        own_school_recommends = Q()
    return Q(highschool=host) | (Q(highschool__isnull=True) & own_school_recommends)


def filing_school(hsadmin, registrations, student, campus=None):
    """The school a recommendation `hsadmin` files on `registrations` is
    recorded for (``StudentRecommendation.highschool``): None for the
    student's own school — every filing when the student's school recommends
    — otherwise the first, by name, of the registrations' recommending schools
    where `hsadmin` holds the permission."""
    from cis.models.highschool import HighSchool
    if hsadmin is None:
        return None
    schools = recommending_school_ids_of(registrations) & {
        p.highschool_id for p in recommender_positions(campus, hsadmin=hsadmin)}
    if not schools or student.highschool_id in schools:
        return None
    return HighSchool.objects.filter(id__in=schools).order_by('name').first()


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

    rule = school_rule()
    q = Q(pk__in=[])
    for position in positions:
        school = recommending_school_q([position.highschool_id], prefix, rule)
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

    rule = school_rule()
    groups = []
    for highschool in HighSchool.objects.filter(
            id__in=recommending_school_ids_of(registrations, rule)).order_by('name'):
        groups.extend(split_by_recommenders(
            highschool,
            registrations.filter(
                recommending_school_q([highschool.id], mode=rule)).distinct('student'),
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
