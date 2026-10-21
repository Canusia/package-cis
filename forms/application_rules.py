"""Cross-field validation rules for the spec-driven application form.

A single field can express "required", "is an email", "is one of these
choices". Anything spanning two fields — an SSN gate, a password match, a
duplicate-student check — cannot live in the field library, so a tenant spec
declares rules alongside its fields:

    APPLICATION_RULES = [
        {'rule': 'ssn_gate',
         'fields': {'number': 'ssn', 'verify': 'verify_ssn', 'optout': 'no_ssn'}},
        {'rule': 'match', 'fields': ['password', 'confirm_password']},
    ]

cis ships only the rules that are genuinely shared across tenants. Anything
tenant-specific (address verification against a particular vendor, say) goes in
the tenant's own `validate(form, cleaned_data)`; see application_spec.

Rule contract: fn(form, cleaned_data, config) -> None. Rules report by calling
form.add_error(); returning normally means "no objection".

`config` is the rule dict itself. `fields` is either a list (positional, for
symmetric rules) or a dict (named roles, for rules where position would be
unreadable). `message` overrides the default wording.
"""
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _


def _named(config, role, default=None):
    fields = config.get('fields') or {}
    if isinstance(fields, dict):
        return fields.get(role, default)
    return default


def _positional(config):
    fields = config.get('fields') or []
    return list(fields) if not isinstance(fields, dict) else list(fields.values())


def ssn_gate(form, cleaned_data, config):
    """The number is required unless the applicant opted out, and the
    confirmation must match it.

    fields: {'number': ..., 'verify': ..., 'optout': ...}
    """
    number_field = _named(config, 'number', 'ssn')
    verify_field = _named(config, 'verify')
    optout_field = _named(config, 'optout')

    number = cleaned_data.get(number_field)
    opted_out = bool(cleaned_data.get(optout_field)) if optout_field else False

    if not number and not opted_out:
        form.add_error(number_field, config.get(
            'message', _('This field is required.')))
        return

    if number and verify_field and cleaned_data.get(verify_field) != number:
        form.add_error(verify_field, config.get(
            'verify_message',
            _('Please verify that you have entered matching values.')))


def match(form, cleaned_data, config):
    """Two fields must be equal (password + confirmation). The error lands on
    the second field, where the user retypes."""
    first, second = _positional(config)[:2]
    if cleaned_data.get(first) != cleaned_data.get(second):
        form.add_error(second, config.get(
            'message', _("The values don't match. Please try again.")))


def fields_must_differ(form, cleaned_data, config):
    """Two fields must NOT be equal — e.g. a parent's phone number cannot be
    the applicant's own. Blank values are ignored; "both empty" is a
    `required` question, not this rule's."""
    first, second = _positional(config)[:2]
    a, b = cleaned_data.get(first), cleaned_data.get(second)
    if a and b and a == b:
        form.add_error(second, config.get(
            'message', _('These two values must be different.')))


def unique_student(form, cleaned_data, config):
    """Reject an applicant who matches another student, using the shared
    duplicate-student rules (cis.services.duplicate_students).

    With `fields`, those fields are the one rule checked (named by `name`,
    default 'identity'); without, the tenant's duplicate-student RULES are.
    The form's bound student is excluded rather than skipping the check —
    complete_signup always binds the student created at the email step, so
    skipping it meant the check never ran on a real application.
    """
    from cis.services import duplicate_students

    rules = None
    if config.get('fields'):
        rules = [{'name': config.get('name', 'identity'),
                  'fields': _positional(config)}]
    duplicate_students.add_duplicate_errors(
        form, cleaned_data, exclude=getattr(form, 'student', None), rules=rules)


RULES = {
    'ssn_gate': ssn_gate,
    'match': match,
    'fields_must_differ': fields_must_differ,
    'unique_student': unique_student,
}


def get_rule(name):
    """Return the rule callable. Unknown names are a configuration error and
    fail loudly at form construction — a typo in tenant config must never
    silently disable a validation rule."""
    try:
        return RULES[name]
    except KeyError:
        raise ImproperlyConfigured(
            f"Unknown application rule {name!r}. Known rules: "
            f"{', '.join(sorted(RULES))}.")


def rule_field_names(config):
    """Every form field a rule config touches — used to decide whether a
    tenant validator has taken ownership of this rule."""
    fields = config.get('fields') or []
    names = list(fields.values()) if isinstance(fields, dict) else list(fields)
    return {n for n in names if n}


def run_rules(form, cleaned_data, rules, owned_fields=frozenset()):
    """Run each configured rule, skipping any whose fields the tenant
    validator owns — for those, the tenant's validate() runs instead."""
    for config in rules or []:
        if owned_fields and rule_field_names(config) & set(owned_fields):
            continue
        get_rule(config['rule'])(form, cleaned_data, config)
