"""Per-field validators for the spec-driven application form (ewu#25 item 7).

Where `application_rules` covers logic spanning two fields, this covers logic
about one field's own value. Normalisers and validators are deliberately ONE
concept, matching Django's own `clean_<field>` convention:

    fn(value, form) -> value

    * raise ValidationError            -> reject
    * return a value                   -> replace the cleaned value
    * return None                      -> keep the original

That last case is what lets stock validators — Django's own, and the
`passwords` package's `LengthValidator` / `ComplexityValidator` /
`DictionaryValidator` — drop in unchanged: they check and return nothing.

A spec entry names them either by registry key or by dotted path, and classes
needing construction pass their arguments:

    {'name': 'first_name', ..., 'validators': ['title_case']},
    {'name': 'password', ..., 'validators': [
        {'validator': 'passwords.validators.LengthValidator',
         'kwargs': {'min_length': 8}},
        'myce_tenant_configs.services.application_form.check_something',
    ]},

cis ships only what is shared across tenants; anything else is a tenant dotted
path. Names resolve at form *construction*, so a typo in tenant config fails
loudly rather than silently disabling a check on submit.
"""
import inspect

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


PHONE_ERROR = _('Enter a valid phone number (e.g. (506) 234-5678) or a number '
                'with an international call prefix.')


def title_case(value, form):
    """`jane VAN der berg` -> `Jane Van Der Berg`."""
    return value.title()


def lower(value, form):
    return value.lower()


def phone_national(value, form):
    """Validate a phone number and normalise it to its national format, so two
    spellings of one number cannot read as two different numbers downstream."""
    from phonenumber_field.phonenumber import PhoneNumber

    try:
        number = PhoneNumber.from_string(value)
        valid = number.is_valid()
    except Exception:
        raise ValidationError(PHONE_ERROR)
    if not valid:
        raise ValidationError(PHONE_ERROR)
    return number.as_national


def future_date(value, form):
    """Graduation dates and the like. Today is not in the future."""
    if value and value <= timezone.localdate():
        raise ValidationError(_('This date must be in the future.'))
    return value


def unique_user_email(value, form):
    """No other account may already use this address — as its email, its
    username, or its secondary email. A student editing their own record is
    not a duplicate of themselves, so the form's bound student is excluded.
    """
    from cis.models.customuser import CustomUser

    value = value.lower()
    qs = CustomUser.objects.filter(
        Q(email=value) | Q(username=value) | Q(secondary_email=value))

    student = getattr(form, 'student', None)
    user = getattr(student, 'user', None)
    if user is not None:
        qs = qs.exclude(pk=user.pk)

    if qs.exists():
        raise ValidationError(
            _('This email is already registered in the system.'), code='invalid')
    return value


VALIDATORS = {
    'title_case': title_case,
    'lower': lower,
    'phone_national': phone_national,
    'future_date': future_date,
    'unique_user_email': unique_user_email,
}


def get_validator(spec):
    """Resolve one spec entry — a registry name, a dotted path, or a dict with
    `validator` plus `kwargs` for classes that need constructing."""
    kwargs = None
    if isinstance(spec, dict):
        kwargs = spec.get('kwargs') or {}
        spec = spec['validator']

    if callable(spec):
        return spec(**kwargs) if kwargs else spec

    if spec in VALIDATORS:
        return VALIDATORS[spec]

    if '.' not in spec:
        raise ImproperlyConfigured(
            f'Unknown application validator {spec!r}. Known validators: '
            f'{", ".join(sorted(VALIDATORS))}. Anything else must be given as '
            f'a dotted path.')

    from cis.forms.application_fields import resolve_dotted

    try:
        resolved = resolve_dotted(spec, call=False)
    except (ValueError, AttributeError) as exc:
        raise ImproperlyConfigured(
            f'Cannot resolve application validator {spec!r}: {exc}')

    if kwargs is not None:
        # a validator *class*, given its arguments
        return resolved(**kwargs)
    return resolved


def resolve_validators(specs):
    """Resolve a spec entry's whole `validators` list."""
    return [get_validator(spec) for spec in (specs or [])]


def _takes_form(fn):
    """Our own validators take (value, form); stock ones take (value)."""
    target = fn if inspect.isfunction(fn) or inspect.ismethod(fn) else getattr(
        fn, '__call__', fn)
    try:
        params = list(inspect.signature(target).parameters.values())
    except (TypeError, ValueError):
        return False
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if any(p.kind == p.VAR_POSITIONAL for p in params):
        return True
    return len(positional) >= 2


def apply_field_validators(form, cleaned_data):
    """Run each field's validators over its cleaned value.

    Blank values are skipped: whether a field may be empty is the `required`
    flag's business, not a validator's. The first error on a field stops that
    field's chain — Django's add_error drops it from cleaned_data, so there is
    no half-normalised value left behind.
    """
    for name, field in form.fields.items():
        validators = getattr(field, 'value_validators', None)
        if not validators or name not in cleaned_data:
            continue

        value = cleaned_data[name]
        if value in (None, ''):
            continue

        for validator in validators:
            try:
                result = (validator(value, form) if _takes_form(validator)
                          else validator(value))
            except ValidationError as exc:
                form.add_error(name, exc)
                break
            if result is not None:
                value = result
        else:
            cleaned_data[name] = value

    return cleaned_data
