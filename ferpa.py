"""FERPA consent per campus (package-cis#65).

One StudentFerpa per (student, campus). Every FERPA check -- the registration
gate, the FERPA page, the onboarding step, the CE tabs and the export -- goes
through here, so "which campus" is decided in one place:

* explicit campus, else the current campus (campus_context / request host);
* multi-campus with no campus set -> no record, not current (never a guess);
* single-campus with no prefixed campus at all -> the campus=None record.
"""
import datetime
import inspect

from cis.services.tenant_services import get_tenant_override, get_tenant_service


def resolve_campus(campus=None):
    if campus is not None:
        return campus
    from cis.campus_context import current_campus_or_none
    return current_campus_or_none()


def ferpa_record(student, campus=None):
    """The student's StudentFerpa for `campus`, or None."""
    from cis.campus_context import is_multi_campus
    from cis.models.student import StudentFerpa

    if student is None:
        return None
    campus = resolve_campus(campus)
    records = StudentFerpa.objects.filter(student=student)
    if campus is not None:
        return records.filter(campus=campus).first()
    if is_multi_campus():
        return None
    return records.filter(campus__isnull=True).first()


def current_term_codes(campus=None):
    """(ok, codes): the campus's open registration term codes. ok is False when
    no terms are configured or they are stale (ewu#45: that is never 'done')."""
    from cis.campus_context import campus_context, is_multi_campus
    from cis.utils import registration_terms_state

    campus = resolve_campus(campus)
    if campus is None and is_multi_campus():
        return False, []
    if campus is not None:
        with campus_context(campus):
            state, terms = registration_terms_state()
    else:
        state, terms = registration_terms_state()
    if state != 'ok':
        return False, []
    return True, list(terms.values_list('code', flat=True))


def ferpa_is_current(student, campus=None, term_codes=None):
    """Signed for this campus, for exactly its open registration terms (the
    codes compared as sets: two querysets need not share an order)."""
    if term_codes is None:
        ok, term_codes = current_term_codes(campus)
        if not ok:
            return False
    if not term_codes:
        return False
    record = ferpa_record(student, campus)
    return record is not None and sorted(record.completed_for or []) == sorted(term_codes)


def ferpa_done_for_term(student, term, campus=None):
    """Signed for `term`'s campus and covering `term` (onboarding step)."""
    if term is None:
        return False
    if campus is None:
        campus = getattr(getattr(term, 'academic_year', None), 'campus', None)
    record = ferpa_record(student, campus)
    return record is not None and term.code in (record.completed_for or [])


def record_ferpa_completion(ferpa, term_codes):
    """Mark `ferpa` as covering `term_codes` today.

    Also mirrors into student.meta['ferpa_completed_for'/'_on'] for one
    release, for tenants and packages that still read the old keys.
    """
    today = datetime.date.today()
    ferpa.completed_for = list(term_codes)
    ferpa.completed_on = today
    ferpa.save(update_fields=['completed_for', 'completed_on'])

    student = ferpa.student
    student.meta = dict(student.meta or {})
    student.meta['ferpa_completed_for'] = list(term_codes)
    student.meta['ferpa_completed_on'] = today.strftime('%m/%d/%Y')
    student.save()


def ferpa_form_class(campus=None):
    """The tenant's FERPA form class for `campus`: its optional
    get_form_class(campus) hook, else StudentFerpaForm."""
    campus = resolve_campus(campus)
    hook = get_tenant_override('ferpa_form', 'get_form_class')
    if hook is not None:
        return hook(campus)
    return get_tenant_service('ferpa_form').StudentFerpaForm


def _accepts(func, name):
    try:
        return name in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


def build_ferpa_form(student, campus=None, *args, **kwargs):
    """Instantiate the campus's form, passing campus= only if it accepts it."""
    campus = resolve_campus(campus)
    form_class = ferpa_form_class(campus)
    if _accepts(form_class.__init__, 'campus'):
        kwargs['campus'] = campus
    return form_class(student, *args, **kwargs)


def ferpa_form_template(campus=None):
    """The tenant's form_template(), with campus when it takes one."""
    func = get_tenant_service('ferpa_form').form_template
    if _accepts(func, 'campus'):
        return func(campus=resolve_campus(campus))
    return func()
