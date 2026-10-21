"""Duplicate-student detection, shared by the signup application and the
Potential Duplicate Students report.

What counts as a duplicate is data: a list of rules, each naming the fields
that together identify one person. An applicant is a duplicate when another
student matches on every field of any one rule. cis ships DEFAULT_RULES; a
tenant replaces them by exporting RULES from
`<TENANT_SERVICES_APP>.services.duplicate_students`, and may extend the field
map with FIELD_LOOKUPS. Both seams are opt-in — a tenant that ships neither
gets the defaults.

What a blocked applicant reads is not here: it is the CE-editable
`complete_signup.dup_student.*` entry of the Signup Page setting's
error_messages, with this module's wording as the fallback.
"""
import json

from django.core.exceptions import ImproperlyConfigured
from django.db.models import CharField, F, Value
from django.db.models.functions import Lower, Replace, Trim

#: Twins share a DOB, school and surname but not a first name, so the second
#: rule does not catch them.
DEFAULT_RULES = [
    {'name': 'ssn', 'fields': ['ssn']},
    {'name': 'identity',
     'fields': ['first_name', 'last_name', 'date_of_birth', 'highschool']},
]

#: field name -> (Student lookup path, how values are compared).
#:   text   — trimmed, case-insensitive
#:   digits — dashes and spaces removed (an SSN typed as 123-45-6789 matches
#:            one imported as 123456789)
#:   exact  — as stored (dates, foreign keys)
FIELD_LOOKUPS = {
    'first_name': ('user__first_name', 'text'),
    'last_name': ('user__last_name', 'text'),
    'middle_name': ('user__middle_name', 'text'),
    'date_of_birth': ('user__date_of_birth', 'exact'),
    'ssn': ('user__ssn', 'digits'),
    'highschool': ('highschool', 'exact'),
}

DEFAULT_MESSAGE = (
    'An account already exists for this student. If it is yours, use Forgot '
    'Password on the login page to get back in, or contact our office for help.')

#: Put on each field of the matched rule, so the inputs are marked without the
#: full message repeating under every one of them.
FIELD_MESSAGE = 'See the message above.'


def _override(attr):
    from cis.services.tenant_services import get_tenant_override
    return get_tenant_override('duplicate_students', attr)


def field_lookups():
    lookups = dict(FIELD_LOOKUPS)
    lookups.update(_override('FIELD_LOOKUPS') or {})
    return lookups


def get_rules():
    """The tenant's RULES, else DEFAULT_RULES — validated, so a typo in tenant
    config fails loudly instead of silently disabling a check."""
    rules = _override('RULES')
    rules = DEFAULT_RULES if rules is None else rules
    known = field_lookups()
    for rule in rules:
        if not rule.get('name') or not rule.get('fields'):
            raise ImproperlyConfigured(
                f'Duplicate-student rule {rule!r} needs a name and fields.')
        unknown = [f for f in rule['fields'] if f not in known]
        if unknown:
            raise ImproperlyConfigured(
                f'Duplicate-student rule {rule["name"]!r} names unknown '
                f'field(s) {unknown}. Known: {", ".join(sorted(known))}. A '
                f'tenant adds fields with FIELD_LOOKUPS.')
    return list(rules)


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _normalize(value, kind):
    if kind == 'text':
        return value.strip().lower()
    if kind == 'digits':
        return ''.join(ch for ch in str(value) if ch.isdigit())
    # A model instance (the chosen high school) compares by its key, since the
    # annotation holds the raw foreign-key column.
    return getattr(value, 'pk', value)


def _db_expression(path, kind):
    if kind == 'text':
        return Lower(Trim(path))
    if kind == 'digits':
        stripped = Replace(F(path), Value('-'), Value(''), output_field=CharField())
        return Replace(stripped, Value(' '), Value(''), output_field=CharField())
    return F(path)


def _annotated(queryset, rule):
    """queryset annotated with one normalized column per rule field
    (`_dup_<field>`), restricted to students who have every one of them."""
    known = field_lookups()
    annotations, filters = {}, {}
    for name in rule['fields']:
        path, kind = known[name]
        alias = f'_dup_{name}'
        annotations[alias] = _db_expression(path, kind)
        filters[f'{path}__isnull'] = False
    qs = queryset.annotate(**annotations).filter(**filters)
    for name in rule['fields']:
        if known[name][1] != 'exact':
            qs = qs.exclude(**{f'_dup_{name}': ''})
    return qs


def find_duplicates(values, exclude=None, rules=None):
    """[(rule, [Student, ...]), ...] for every rule `values` matches.

    `values` maps field names to answers — a form's cleaned_data works as is.
    A rule with any blank answer is skipped: an applicant who gave no SSN
    cannot match on SSN. `exclude` is the applicant's own record, so a student
    is never a duplicate of themselves.
    """
    from cis.models.student import Student

    rules = get_rules() if rules is None else rules
    known = field_lookups()
    matches = []
    for rule in rules:
        answers = {name: values.get(name) for name in rule['fields']}
        if any(_blank(v) for v in answers.values()):
            continue
        qs = _annotated(Student.objects.all(), rule)
        for name, value in answers.items():
            qs = qs.filter(**{f'_dup_{name}': _normalize(value, known[name][1])})
        if exclude is not None:
            qs = qs.exclude(pk=exclude.pk)
        found = list(qs.select_related('user')[:10])
        if found:
            matches.append((rule, found))
    return matches


def find_duplicate_groups(rules=None):
    """[(rule, [Student, ...]), ...] — one entry per set of two or more
    students who match each other on every field of a rule. For the report."""
    from cis.models.student import Student

    rules = get_rules() if rules is None else rules
    groups = []
    for rule in rules:
        aliases = [f'_dup_{name}' for name in rule['fields']]
        qs = _annotated(Student.objects.all(), rule)
        buckets = {}
        for row in qs.values_list('pk', *aliases).iterator():
            buckets.setdefault(tuple(row[1:]), []).append(row[0])
        dup_ids = [ids for ids in buckets.values() if len(ids) > 1]
        if not dup_ids:
            continue
        students = Student.objects.select_related(
            'user', 'highschool').in_bulk(
            [pk for ids in dup_ids for pk in ids])
        for ids in dup_ids:
            groups.append((rule, [students[pk] for pk in ids]))
    return groups


def message_for(rule):
    """The CE-configured message for this rule: dup_student.<rule name>, then
    dup_student.default, then DEFAULT_MESSAGE."""
    from cis.settings.signup import signup

    try:
        config = json.loads(signup.from_db().get('error_messages', '{}'))
    except (json.JSONDecodeError, TypeError, AttributeError):
        config = {}
    node = (config.get('complete_signup') or {}).get('dup_student') or {}
    if not isinstance(node, dict):
        node = {}
    return node.get(rule['name']) or node.get('default') or DEFAULT_MESSAGE


def add_duplicate_errors(form, cleaned_data, exclude=None, rules=None):
    """Block a duplicate applicant: one form-level error carrying the message
    for the first matching rule, and FIELD_MESSAGE on each of its fields the
    form has. Returns True when the applicant was blocked.

    A rule whose fields are all read-only on this form (a post-SIS profile
    edit) is skipped: the student cannot change those answers, so an error
    would only make the profile impossible to save.
    """
    rules = get_rules() if rules is None else rules
    readonly = set(getattr(form, 'readonly_fields', ()) or ())
    if readonly:
        rules = [r for r in rules if not set(r['fields']) <= readonly]
    matches = find_duplicates(cleaned_data, exclude=exclude, rules=rules)
    if not matches:
        return False
    rule = matches[0][0]
    form.add_error(None, message_for(rule))
    for name in rule['fields']:
        if name in form.fields and name not in form.errors:
            form.add_error(name, FIELD_MESSAGE)
    return True
