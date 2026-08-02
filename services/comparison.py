"""Dimension-parameterized comparison service.

The ONLY module that knows Term from AcademicYear. Adding a dimension is a
registry entry here -- never a new metric.
"""
import uuid
from dataclasses import dataclass
from typing import List, Optional, Type

from django.db.models import Model, Q
from django.http import Http404

MAX_COMPARE_IDS = 3


@dataclass(frozen=True)
class Dimension:
    """One comparable axis (a Term, an AcademicYear, ...).

    `label_field=None` renders records with `str(record)`. The term dimension
    needs this: `Term.label` is "Fall", which repeats every academic year,
    while `Term.__str__` is "2026-2027, Fall".
    """
    slug: str
    model: Type[Model]
    label_field: Optional[str]
    registration_path: str
    section_path: str
    ordering: str
    noun: str

    def label(self, record):
        if self.label_field is None:
            return str(record)
        return getattr(record, self.label_field)


def _build_registry():
    from cis.models.term import AcademicYear, Term
    return {
        'term': Dimension(
            slug='term', model=Term, label_field=None,
            registration_path='class_section__term',
            section_path='term',
            ordering='-code', noun='Term',
        ),
        'academic_year': Dimension(
            slug='academic_year', model=AcademicYear, label_field='name',
            registration_path='class_section__term__academic_year',
            section_path='term__academic_year',
            ordering='-code', noun='Academic Year',
        ),
    }


COMPARE_DIMENSIONS = _build_registry()


def get_dimension(slug):
    """Resolve a dimension slug, 404ing on anything unregistered."""
    try:
        return COMPARE_DIMENSIONS[slug]
    except KeyError:
        raise Http404(f'Unknown comparison dimension: {slug}')


NO_CAMPUS = 'none'


@dataclass(frozen=True)
class CompareFilters:
    dimension: Dimension
    ids: List[str]
    statuses: List[str]
    campus_ids: List[str]
    include_null_campus: bool
    section_statuses: List[str]


def _valid_uuids(values):
    """Keep only well-formed UUID strings, preserving input order."""
    out = []
    for v in values:
        try:
            out.append(str(uuid.UUID(str(v))))
        except (ValueError, AttributeError, TypeError):
            pass
    return out


def parse_filters(request, dimension):
    """Parse + validate query params. The sole campus-gate enforcement point.

    Raises ValidationError (400) for a 4th id, an unknown registration status,
    or an unknown section status. Silently drops non-UUID ids and campus ids
    outside the user's gate -- a probe should learn nothing from the response.
    """
    from rest_framework.exceptions import ValidationError

    from cis.campus_gate import get_accessible_campuses, get_process_campus_ids
    from cis.models.section import ClassSection, StudentRegistration
    from cis.utils import user_has_cis_role

    raw_ids = request.GET.getlist('id')
    if len(raw_ids) > MAX_COMPARE_IDS:
        raise ValidationError(
            {'error': f'Select at most {MAX_COMPARE_IDS} '
                      f'{dimension.noun.lower()}s to compare.'})
    ids = _valid_uuids(raw_ids)

    valid_statuses = [v for v, _ in StudentRegistration.STATUS_OPTIONS]
    statuses = request.GET.getlist('status') or list(valid_statuses)
    unknown = set(statuses) - set(valid_statuses)
    if unknown:
        raise ValidationError(
            {'error': f'Unknown registration status: {sorted(unknown)[0]}'})

    valid_section_statuses = [v for v, _ in ClassSection.CLASS_STATUS]
    section_statuses = request.GET.getlist('section_status') or ['A']
    unknown = set(section_statuses) - set(valid_section_statuses)
    if unknown:
        raise ValidationError(
            {'error': f'Unknown section status: {sorted(unknown)[0]}'})

    gate_ids = set(get_process_campus_ids(request.user))
    # A user who cannot process campuses (non-CIS-role, non-superuser) can
    # never see null-campus rows -- whether they ask for them by default or
    # explicitly via campus=none.
    may_process = (
        getattr(request.user, 'is_superuser', False)
        or user_has_cis_role(request.user)
    )
    raw_campus = request.GET.getlist('campus')
    if raw_campus:
        include_null_campus = may_process and (NO_CAMPUS in raw_campus)
        # Drop out-of-gate ids silently: this is gate enforcement.
        campus_ids = [c for c in _valid_uuids(raw_campus) if c in gate_ids]
    else:
        include_null_campus = may_process
        campus_ids = [
            str(pk) for pk
            in get_accessible_campuses(request.user).values_list('id', flat=True)
        ]

    return CompareFilters(
        dimension=dimension, ids=ids, statuses=statuses,
        campus_ids=campus_ids, include_null_campus=include_null_campus,
        section_statuses=section_statuses,
    )


NO_HIGH_SCHOOL = '(No high school)'
TOTAL_CREDITS_CATEGORY = 'Total credits'


@dataclass(frozen=True)
class Metric:
    key: str
    title: str
    base: str          # 'registration' | 'section'
    presentation: str  # 'chart' | 'chart_and_table'


METRICS = {m.key: m for m in [
    Metric('registrations_by_status', 'Registrations by Status',
           'registration', 'chart'),
    Metric('registrations_by_highschool', 'Registrations by High School',
           'registration', 'chart_and_table'),
    Metric('registrations_by_course', 'Registrations by Course',
           'registration', 'chart_and_table'),
    Metric('sections_by_course', 'Sections Offered by Course',
           'section', 'chart_and_table'),
    Metric('sections_by_highschool', 'Sections by High School',
           'section', 'chart_and_table'),
    Metric('total_credits', 'Total Credits', 'registration', 'chart'),
]}


def _course_label(prefix):
    """Concat `<catalog_number> — <title>` at the DB level."""
    from django.db.models import CharField, Value
    from django.db.models.functions import Concat
    return Concat(
        f'{prefix}catalog_number', Value(' — '), f'{prefix}title',
        output_field=CharField())


def _highschool_label(prefix):
    from django.db.models import CharField, Value
    from django.db.models.functions import Coalesce
    return Coalesce(
        f'{prefix}name', Value(NO_HIGH_SCHOOL), output_field=CharField())


def _registration_qs(filters):
    from cis.models.section import StudentRegistration
    dim = filters.dimension
    return StudentRegistration.objects.filter(
        campus_q('class_section__course__campus', filters),
        **{
            f'{dim.registration_path}__id__in': filters.ids,
            'status__in': filters.statuses,
            'class_section__status__in': filters.section_statuses,
        }
    )


def _section_qs(filters):
    from cis.models.section import ClassSection
    dim = filters.dimension
    return ClassSection.objects.filter(
        campus_q('course__campus', filters),
        **{
            f'{dim.section_path}__id__in': filters.ids,
            'status__in': filters.section_statuses,
        }
    )


def _category_expression(key):
    """The grouping expression for a metric, or None for dimension-only."""
    from django.db.models import F
    return {
        'registrations_by_status': F('status'),
        'registrations_by_highschool': _highschool_label(
            'student__highschool__'),
        'registrations_by_course': _course_label('class_section__course__'),
        'sections_by_course': _course_label('course__'),
        'sections_by_highschool': _highschool_label('highschool__'),
        'total_credits': None,
    }[key]


def run_metric(filters, key):
    """One grouped aggregate covering every selected dimension record."""
    from django.db.models import Count, F, Sum

    metric = METRICS[key]
    if not filters.ids:
        return []

    dim = filters.dimension
    if metric.base == 'registration':
        qs = _registration_qs(filters)
        dim_path = f'{dim.registration_path}__id'
    else:
        qs = _section_qs(filters)
        dim_path = f'{dim.section_path}__id'

    aggregate = (
        Sum('class_section__course__credit_hours') if key == 'total_credits'
        else Count('id')
    )
    category = _category_expression(key)

    if category is None:
        rows = qs.values(dimension_id=F(dim_path)).annotate(value=aggregate)
        return [
            {'dimension_id': str(r['dimension_id']),
             'category': TOTAL_CREDITS_CATEGORY,
             'value': r['value'] if r['value'] is not None else 0}
            for r in rows
        ]

    rows = (qs.values(dimension_id=F(dim_path), category=category)
              .annotate(value=aggregate))
    return [
        {'dimension_id': str(r['dimension_id']),
         'category': r['category'],
         'value': r['value'] if r['value'] is not None else 0}
        for r in rows
    ]


def dimension_list(filters):
    """Selected records as [{'id','label'}], in the user's selection order."""
    dim = filters.dimension
    qs = dim.model.objects.filter(id__in=filters.ids)
    if dim.slug == 'term':
        qs = qs.select_related('academic_year')
    by_id = {str(r.id): r for r in qs}
    return [{'id': i, 'label': dim.label(by_id[i])}
            for i in filters.ids if i in by_id]


def build_payload(filters):
    """Everything the panel needs for one comparison, in one response."""
    return {
        'dimensions': dimension_list(filters),
        'filters': {
            'statuses': filters.statuses,
            'section_statuses': filters.section_statuses,
            'campus_ids': filters.campus_ids,
            'include_null_campus': filters.include_null_campus,
        },
        'metrics': {
            key: {
                'title': metric.title,
                'presentation': metric.presentation,
                'rows': run_metric(filters, key),
            }
            for key, metric in METRICS.items()
        },
    }


NO_CAMPUS_LABEL = '(No campus)'


def build_compare_context(request, dimension_slug):
    """Filter-panel choices for one dimension. Called by both index views."""
    from cis.campus_gate import get_accessible_campuses, scope_queryset_by_campus
    from cis.models.section import ClassSection, StudentRegistration

    dim = get_dimension(dimension_slug)
    records = dim.model.objects.all().order_by(dim.ordering)

    # Campus-scope the selectable records + tag each with its campus so the
    # academic-years panel can cascade off a campus selector.
    if dim.slug == 'academic_year':
        records = scope_queryset_by_campus(
            records.select_related('campus'), request.user, campus_path='campus')

        def _campus_id(r):
            return str(r.campus_id) if r.campus_id else ''
    elif dim.slug == 'term':
        records = scope_queryset_by_campus(
            records.select_related('academic_year__campus'),
            request.user, campus_path='academic_year__campus')

        def _campus_id(r):
            ay = r.academic_year
            return str(ay.campus_id) if ay and ay.campus_id else ''
    else:
        def _campus_id(r):
            return ''

    campuses = [
        {'id': str(c.id), 'label': c.name}
        for c in get_accessible_campuses(request.user).order_by('name')
    ]
    campuses.append({'id': NO_CAMPUS, 'label': NO_CAMPUS_LABEL})

    return {
        'compare_dimension': dim.slug,
        'compare_noun': dim.noun,
        'compare_records': [
            {'id': str(r.id), 'label': dim.label(r), 'campus_id': _campus_id(r)}
            for r in records],
        'compare_statuses': list(StudentRegistration.STATUS_OPTIONS),
        'compare_campuses': campuses,
        'compare_section_statuses': list(ClassSection.CLASS_STATUS),
        'compare_metric_cards': [
            (m.key, m.title) for m in METRICS.values()],
    }


def campus_q(prefix, filters):
    """Q over `prefix` (a campus FK path) honoring the resolved campus filter.

    Selecting neither a campus nor "(No campus)" deliberately matches nothing,
    rather than silently degrading to "everything".
    """
    if not filters.campus_ids and not filters.include_null_campus:
        return Q(pk__in=[])
    q = Q()
    if filters.campus_ids:
        q |= Q(**{f'{prefix}__id__in': filters.campus_ids})
    if filters.include_null_campus:
        q |= Q(**{f'{prefix}__isnull': True})
    return q
