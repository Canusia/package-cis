"""Reusable application field *types*. Each builder turns a tenant spec entry
into one or more with_meta-wrapped Django fields. cis ships generic types only;
the tenant spec (in myce_tenant_configs) supplies content and field selection.

Builder contract: fn(entry, ctx) -> list[(name, field)].

`ctx` carries the runtime state a field may need at construction time —
`student` and `request` — because types like `model_choice` and `date` cannot
be built from the spec dict alone. Composite types (e.g. `password_pair`,
`ssn`) return several fields.

Spec entry keys read here:
    name, type, label            required
    help_text, required          `required` defaults to True (Django's own
                                 default); set it False explicitly to opt out
    disabled                     render greyed AND discard any posted value
    target, attr                 storage routing, see with_meta
    validate, depends_on,        the rest of the with_meta contract, passed
    copy_when                    straight through
    choices, choices_from        choice/multichoice; `choices_from` is a dotted
                                 path to an existing constant or callable so a
                                 tenant need not copy (and drift from) a model's
                                 option list
    attrs                        HTML attrs merged onto the widget (bootstrap
                                 classes, placeholders, data-*)
    max_length, initial          text-backed types only / any type
    widget                       dotted path to a widget class OR to a factory
                                 returning a configured instance — the second
                                 form is how a tenant configures a widget whose
                                 settings cis must not learn about (a
                                 SelectDateWidget year range, say)
    field_class                  dotted path to a Field class replacing the
                                 type's default (e.g. form_fields.ReadOnlyField)
    validators                   per-field validators/normalisers; see
                                 application_validators
"""
import importlib

from django import forms

from cis.forms.utils import with_meta
from cis.forms.application_validators import resolve_validators


def resolve_dotted(path, call=True):
    """Import `a.b.c.NAME` (or a deeper attribute chain such as
    `...HighSchool.objects.all`) and return the object, calling it when the
    resolved attribute is callable.

    `call=False` returns the attribute itself — used for `field_class`, which
    cis constructs with the spec's own kwargs rather than calling bare."""
    parts = path.split('.')
    module = None
    rest = []
    for i in range(len(parts) - 1, 0, -1):
        try:
            module = importlib.import_module('.'.join(parts[:i]))
        except ModuleNotFoundError:
            continue
        rest = parts[i:]
        break
    if module is None:
        raise ValueError(f'cannot resolve dotted path: {path}')

    obj = module
    for attr in rest:
        obj = getattr(obj, attr)
    return obj() if (call and callable(obj)) else obj


def _meta(entry, field, target=None):
    """Attach the full with_meta contract from the spec entry."""
    return with_meta(
        field,
        target=target or entry['target'],
        path=entry.get('attr'),
        validate=entry.get('validate'),
        depends_on=entry.get('depends_on'),
        copy_when=entry.get('copy_when'),
    )


def _required(entry):
    return entry.get('required', True)


def _common(entry, **overrides):
    """Field kwargs every type shares."""
    kwargs = {
        'label': entry.get('label', ''),
        'required': _required(entry),
        'help_text': entry.get('help_text', ''),
    }
    if entry.get('initial') is not None:
        kwargs['initial'] = entry['initial']
    if entry.get('disabled'):
        # Django's `disabled` greys the input AND makes the field ignore any
        # submitted value — the security half, which a widget attr alone does
        # not give. Needed for pre-verified values (a confirmed email address).
        kwargs['disabled'] = True
    kwargs.update(overrides)
    return kwargs


def _text_kwargs(entry, **overrides):
    """`max_length` may only reach the text-backed types — ChoiceField,
    DateField and BooleanField all raise on it."""
    kwargs = _common(entry, **overrides)
    if entry.get('max_length'):
        kwargs['max_length'] = entry['max_length']
    return kwargs


def _build(entry, field_class, kwargs, overridable=True):
    """Construct the field, honouring the spec's `field_class` / `widget`
    overrides, then merge its `attrs`.

    `attrs` merge LAST, after any widget swap — otherwise overriding a widget
    would silently drop that field's bootstrap classes and maxlength.

    `overridable=False` is for the secondary halves of a composite (the SSN
    confirmation, the password confirmation): one `widget` key in the entry
    cannot sensibly mean two different fields, so it applies to the primary.
    """
    if overridable and entry.get('field_class'):
        field_class = resolve_dotted(entry['field_class'], call=False)
    if overridable and entry.get('widget'):
        # calling the resolved object covers both a widget class and a factory
        # returning an already-configured instance
        kwargs = dict(kwargs, widget=resolve_dotted(entry['widget']))

    field = field_class(**kwargs)

    if entry.get('attrs'):
        field.widget.attrs.update(entry['attrs'])
    return field


def _choices(entry):
    """Accept `[(value, label), ...]`, bare strings (value == label), or a
    dotted path in `choices_from`."""
    raw = entry.get('choices', [])
    if entry.get('choices_from'):
        raw = resolve_dotted(entry['choices_from'])
    return [c if isinstance(c, (tuple, list)) else (c, c) for c in raw]


def _text(entry, ctx):
    f = _build(entry, forms.CharField, _text_kwargs(entry))
    return [(entry['name'], _meta(entry, f))]


def _email(entry, ctx):
    f = _build(entry, forms.EmailField, _text_kwargs(entry))
    return [(entry['name'], _meta(entry, f))]


def _choice(entry, ctx):
    f = _build(entry, forms.ChoiceField,
               _common(entry, choices=_choices(entry)))
    return [(entry['name'], _meta(entry, f))]


def _multichoice(entry, ctx):
    f = _build(entry, forms.MultipleChoiceField,
               _common(entry, choices=_choices(entry)))
    return [(entry['name'], _meta(entry, f))]


def _agreement(entry, ctx):
    # A required checkbox whose label is the (long) agreement text.
    f = _build(entry, forms.BooleanField, _common(entry))
    return [(entry['name'], _meta(entry, f))]


def _readonly_disclosure(entry, ctx):
    # Display-only text rendered above a following field; never persisted.
    # A tenant wanting styled block text rather than a textarea points
    # `field_class` / `widget` at the form_fields pair (ReadOnlyField +
    # LongLabelWidget); the default stays dependency-free.
    kwargs = {
        'label': entry.get('label', ''),
        'required': False,
        'disabled': True,
        'initial': entry.get('text', ''),
        'widget': forms.Textarea(attrs={'readonly': True, 'rows': 4}),
    }
    f = _build(entry, forms.CharField, kwargs)
    return [(entry['name'], _meta(entry, f, target='skip'))]


def _date(entry, ctx):
    """A date picker. `min` / `max` (ISO strings) become widget bounds; a spec
    whose bounds are computed (e.g. the graduation-year window from the
    registrations setting) points `min_from` / `max_from` at a callable."""
    attrs = {'type': 'date'}
    for bound in ('min', 'max'):
        value = entry.get(bound)
        if entry.get(f'{bound}_from'):
            value = resolve_dotted(entry[f'{bound}_from'])
        if value:
            attrs[bound] = value
    f = _build(entry, forms.DateField,
               _common(entry, widget=forms.DateInput(attrs=attrs)))
    return [(entry['name'], _meta(entry, f))]


def _model_choice(entry, ctx):
    """A select backed by a queryset. `queryset` is a dotted path to a queryset
    or to a callable returning one (e.g.
    'cis.models.highschool.HighSchool.objects.all'), so a tenant can express
    "active, non-CTE high schools" as a manager method in its own app."""
    queryset = resolve_dotted(entry['queryset'])
    f = _build(entry, forms.ModelChoiceField,
               _common(entry, queryset=queryset,
                       empty_label=entry.get('empty_label', '---')))
    return [(entry['name'], _meta(entry, f))]


def _password_pair(entry, ctx):
    """Password + confirmation. Never written by the storage layer — the form
    hashes it onto the user — so both halves are `skip`."""
    name = entry['name']
    confirm_name = entry.get('confirm_name', f'confirm_{name}')
    password = _build(entry, forms.CharField,
                      _text_kwargs(entry, widget=forms.PasswordInput()))
    confirm = _build(
        entry, forms.CharField,
        _text_kwargs(entry, widget=forms.PasswordInput(),
                     label=entry.get('confirm_label', 'Confirm Password'),
                     help_text='', initial=None),
        overridable=False)
    return [
        (name, _meta(entry, password, target='skip')),
        (confirm_name, _meta(entry, confirm, target='skip')),
    ]


def _signature(entry, ctx):
    """Typed signature — one line the applicant types their name into."""
    f = _build(entry, forms.CharField,
               _text_kwargs(entry,
                            widget=forms.TextInput(attrs={'autocomplete': 'off'}),
                            help_text=entry.get('help_text',
                                                'Please type your name')))
    return [(entry['name'], _meta(entry, f))]


def _ssn(entry, ctx):
    """SSN composite: the number, a confirmation of it, and an opt-out
    checkbox. Both text halves are optional at field level — whether one is
    *demanded* depends on the opt-out, which is a cross-field rule the form
    applies, not something a single field can express.

    The disclosure text above it stays a separate `readonly_disclosure` entry,
    so the wording remains tenant-side.
    """
    name = entry['name']
    verify_name = entry.get('verify_name', f'verify_{name}')
    optout_name = entry.get('optout_name', f'no_{name}')

    number = _build(entry, forms.CharField, _text_kwargs(entry, required=False))
    verify = _build(
        entry, forms.CharField,
        _text_kwargs(entry, required=False, help_text='', initial=None,
                     label=entry.get('verify_label', 'Re-enter to confirm')),
        overridable=False)
    optout = _build(
        entry, forms.BooleanField,
        {'required': False, 'help_text': '',
         'label': entry.get('optout_label',
                            'I do not have a Social Security Number')},
        overridable=False)

    return [
        (name, _meta(entry, number)),
        # the confirmation exists only to be compared against the number
        (verify_name, _meta(entry, verify, target='skip')),
        # the opt-out is an answer, not a column: it belongs in student.meta
        (optout_name, _meta(entry, optout, target='meta')),
    ]


FIELD_TYPES = {
    'text': _text,
    'email': _email,
    'choice': _choice,
    'multichoice': _multichoice,
    'agreement': _agreement,
    'readonly_disclosure': _readonly_disclosure,
    'date': _date,
    'model_choice': _model_choice,
    'password_pair': _password_pair,
    'signature': _signature,
    'ssn': _ssn,
}


def build_fields(entry, ctx=None):
    """Return [(name, field), ...] for a spec entry. KeyError on unknown type.

    `ctx` is the runtime context ({'student': ..., 'request': ...}) handed to
    every builder; it is optional so callers needing only declarative types
    (and tests) can omit it."""
    built = FIELD_TYPES[entry['type']](entry, ctx or {})

    # Resolve unconditionally, so a typo raises even for an entry whose type
    # builds no field under its own name.
    validators = resolve_validators(entry.get('validators'))
    if validators:
        # A composite's confirmation/opt-out halves are not the thing the
        # entry's validators describe; only the named field carries them.
        for name, field in built:
            if name == entry['name']:
                field.value_validators = validators

    return built
