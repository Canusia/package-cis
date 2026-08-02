import json

from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.validators import validate_html_short_code, validate_profile_display
from ..models.settings import Setting


# Signup mechanics never belong on the editable profile form. Generic across
# tenants, so unlike the field list this stays in cis.
SIGNUP_MECHANIC_FIELDS = ('password', 'confirm_password', 'signature')

_profile_fields_cache = None


def profile_fields():
    """Every profile field an admin may mark editable: the tenant form's field
    set minus signup mechanics, in declaration order.

    Derived rather than listed. The literal this replaced carried a "keep in
    sync with StudentProfileForm" comment and had already drifted — it parked
    start_date and graduation_date at the end, while default_field_weights()
    seeds weights straight from base_fields. Deriving removes the drift and the
    last tenant field names from cis.

    Cached per process: base_fields is fixed at class creation, so re-deriving
    on every call would buy nothing. Tests that swap the tenant form must call
    reset_profile_fields_cache().
    """
    global _profile_fields_cache
    if _profile_fields_cache is None:
        from cis.forms.student_profile import StudentProfileForm
        _profile_fields_cache = [
            name for name in StudentProfileForm.base_fields
            if name not in SIGNUP_MECHANIC_FIELDS
        ]
    return list(_profile_fields_cache)


def reset_profile_fields_cache():
    """Drop the cached vocabulary. For tests that patch the tenant form."""
    global _profile_fields_cache
    _profile_fields_cache = None


def message_fields():
    """Field names whose Label and Help Text an admin may configure — the
    profile fields plus the signup mechanics, which have wording but are not
    editable."""
    return profile_fields() + list(SIGNUP_MECHANIC_FIELDS)


DEFAULT_LOCKED_MESSAGE = (
    'Your application is currently under review. '
    'Editing is disabled until review is complete.'
)
DEFAULT_EDITABLE_MESSAGE = (
    'Please review your information below and update anything that has changed.'
)
DEFAULT_REVIEW_INTRO = (
    'Please review the information below and confirm it is current for the new term.'
)
DEFAULT_REVIEW_TEMPLATE = """<div class="details">
  <div class="row p-2">
    <div class="col-md-4 mt-2"><div class="detail_label">FIRST NAME</div><div>{{ student.user.first_name }}</div></div>
    <div class="col-md-4 mt-2"><div class="detail_label">LAST NAME</div><div>{{ student.user.last_name }}</div></div>
    <div class="col-md-4 mt-2"><div class="detail_label">MIDDLE NAME</div><div>{{ student.middle_name }}</div></div>
  </div>
  <div class="row p-2">
    <div class="col-md-4 mt-2"><div class="detail_label">PRIMARY EMAIL</div><div>{{ student.user.email }}</div></div>
    <div class="col-md-4 mt-2"><div class="detail_label">CELL PHONE</div><div>{{ student.user.primary_phone }}</div></div>
    <div class="col-md-4 mt-2"></div>
  </div>
  <div class="row p-2">
    <div class="col-md-4 mt-2"><div class="detail_label">HOME ADDRESS</div><div>{{ student.user.address1 }}</div></div>
    <div class="col-md-4 mt-2"><div class="detail_label">CITY</div><div>{{ student.user.city }}</div></div>
    <div class="col-md-4 mt-2"><div class="detail_label">ZIP CODE</div><div>{{ student.user.postal_code }}</div></div>
  </div>
  <div class="row p-2">
    <div class="col-md-4 mt-2"><div class="detail_label">HIGH SCHOOL</div><div>{{ student.highschool }}</div></div>
    <div class="col-md-4 mt-2"></div>
    <div class="col-md-4 mt-2"></div>
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Configurable Student-detail (Student.asHTML) layout
# ---------------------------------------------------------------------------
# DEFAULT_PROFILE_DISPLAY is the exact rows/columns structure historically
# hardcoded inside Student.asHTML. It is the fallback used whenever the
# `profile_display` setting is unset, blank, or invalid, so asHTML output is
# unchanged until an admin configures it. Each row is a list of columns; a
# column is either a bare field-path string (label derived by uppercasing and
# replacing '_' with space), the empty string '' (blank cell), or a dict
# {'field': <dotted path>, 'label': <text>}. Consumed by cis.utils.model_as_HTML.
DEFAULT_PROFILE_DISPLAY = [
    [
        {'field': 'user.first_name', 'label': 'First Name'},
        {'field': 'user.last_name', 'label': 'Last Name'},
        {'field': 'user.middle_name', 'label': 'Middle Name'},
    ],
    [
        {'field': 'user.email', 'label': 'Primary Email'},
        {'field': 'user.psid', 'label': 'EMPLID'},
        'sis_id',
    ],
    [
        'parent_email',
        'parent_name',
        'parent_phone',
    ],
    [
        'highschool', 'graduation_year',
        'cte',
    ],
    [
        'grade_level',
    ],
    [
        '_gender',
        {'field': 'user.primary_phone', 'label': 'Cell Phone'},
        {'field': 'user._date_of_birth', 'label': 'Date of Birth'},
    ],
    [
        {'field': 'sexy_address', 'label': 'Mailing Address'},
        '',
        '',
    ],
    [
        {'field': 'id', 'label': 'Internal ID'},
        {'field': 'ferpa_completed_on', 'label': 'FERPA Completed On'},
        {'field': 'sis_sent_on', 'label': 'Sent to SIS On'},
    ],
]

# Field paths used by DEFAULT_PROFILE_DISPLAY that are NOT StudentProfileForm
# fields (computed model properties / related-object dotted paths / model
# columns). The validator's allow-set is StudentProfileForm.base_fields UNION
# this set UNION '' (blank cell). Keep this list a superset of every non-form
# key in DEFAULT_PROFILE_DISPLAY.
EXTRA_DISPLAY_FIELD_PATHS = {
    'user.first_name': 'First Name',
    'user.last_name': 'Last Name',
    'user.middle_name': 'Middle Name',
    'user.email': 'Primary Email',
    'user.psid': 'EMPLID',
    'user.primary_phone': 'Cell Phone',
    'user._date_of_birth': 'Date of Birth',
    'user.id': 'User ID',
    'sis_id': 'SIS Id',
    'parent_name': 'Parent Name',
    'parent_phone': 'Parent Phone',
    'highschool': 'Highschool',
    'graduation_year': 'Graduation Year',
    'grade_level': 'Grade Level',
    '_gender': 'Gender',
    'sexy_address': 'Mailing Address',
    'id': 'Internal ID',
    'ferpa_completed_on': 'FERPA Completed On',
    'sis_sent_on': 'Sent to SIS On',
}


# ---------------------------------------------------------------------------
# Profile fields: order (weights) + editability + label + help text, one row
# per field
# ---------------------------------------------------------------------------
# All four facets are configured in a single table so the field list isn't
# repeated: each row carries a drag handle, a caret expanding a detail row with
# the field's Label and Help Text, the field name, an "editable" checkbox, and a
# weight. They are still *stored* as three independent flat keys —
# `field_weights` ({field_name: int}), `editable_fields` ([field_name]) and
# `field_messages` ({field_name: {'label': str, 'help_text': str}}) — which is
# what every consumer reads.
#
# Lower weights render first. Weights drive the field order of every
# StudentProfileForm descendant (student profile, editable profile, CE student
# forms) *and* of the spec-driven application form, so a tenant orders its
# fields once. Fields with no weight are not banished to the end: they keep
# their position relative to the weighted field that precedes them (see
# `order_field_names`), so partially-weighted configs behave predictably.


def order_field_names(field_names, weights):
    """Return `field_names` reordered by `weights` ({name: number}).

    Unweighted names inherit the weight of the preceding name plus an epsilon,
    which keeps them anchored where they already were. Ties fall back to the
    original position, so the ordering is stable and a weightless config is a
    no-op.
    """
    if not weights:
        return list(field_names)

    keyed = []
    running = 0.0
    for index, name in enumerate(field_names):
        weight = weights.get(name)
        if weight is None:
            running += 1e-6
        else:
            try:
                running = float(weight)
            except (TypeError, ValueError):
                running += 1e-6
        keyed.append((running, index, name))

    return [name for _, _, name in sorted(keyed)]


def profile_field_names(spec=None):
    """The profile-field vocabulary: profile_fields(), plus any field the
    tenant's application spec declares that the legacy form does not.

    profile_fields() is derived from StudentProfileForm, so without this a field
    existing only in APPLICATION_FIELDS would get no settings row, no
    configurable label or help text, and no seeded weight — the tenant would
    not actually own its own field list. Signup mechanics stay out, exactly as
    they do for the legacy vocabulary.

    Returns a plain list; ewu (which ships no spec) gets profile_fields() back
    unchanged.
    """
    if spec is None:
        from cis.forms.application_spec import get_application_fields
        spec = get_application_fields() or []

    names = profile_fields()
    for entry in spec:
        name = entry.get('name')
        if not name or name in names or name in SIGNUP_MECHANIC_FIELDS:
            continue
        names.append(name)
    return names


def default_field_weights(spec=None):
    """Seed weights (10, 20, 30, …) in the order fields are declared on
    StudentProfileForm, so installing the default is order-preserving. Any
    vocabulary entry the form doesn't declare is appended after — which is how
    spec-only fields get a weight at all."""
    from cis.forms.student_profile import StudentProfileForm

    vocabulary = profile_field_names(spec=spec)
    declared = [n for n in StudentProfileForm.base_fields if n in vocabulary]
    trailing = [n for n in vocabulary if n not in declared]
    return {name: (i + 1) * 10 for i, name in enumerate(declared + trailing)}


class ProfileFieldsWidget(forms.Widget):
    """One row per profile field — drag handle, caret, editable checkbox,
    weight — rendered in current weight order, each followed by a hidden detail
    row holding that field's Label and Help Text inputs (revealed by the
    caret). Below the main table, the three signup-mechanic fields render with
    Label and Help Text only."""

    def _messages_from_data(self, data, name):
        """Collect {field: {'label': …, 'help_text': …}} from POST, skipping
        fields where both inputs are blank."""
        messages = {}
        for field_name in profile_field_names() + list(SIGNUP_MECHANIC_FIELDS):
            entry = {}
            label = (data.get(f'{name}_label_{field_name}') or '').strip()
            help_text = (data.get(f'{name}_help_{field_name}') or '').strip()
            if label:
                entry['label'] = label
            if help_text:
                entry['help_text'] = help_text
            if entry:
                messages[field_name] = entry
        return messages

    def value_from_datadict(self, data, files, name):
        getlist = getattr(data, 'getlist', None)
        editable = (getlist(f'{name}_editable') if getlist
                    else data.get(f'{name}_editable') or [])
        weights = {}
        for field_name in profile_field_names():
            raw = data.get(f'{name}_weight_{field_name}')
            if raw in (None, ''):
                continue
            weights[field_name] = raw
        # Unknown names are passed through, not filtered, so the field can
        # reject them (they can only come from a tampered POST).
        return {'editable': list(editable), 'weights': weights,
                'messages': self._messages_from_data(data, name)}

    def _detail_row(self, name, field_name, message, columns):
        """Collapsed full-width row holding the label + help text inputs."""
        return format_html(
            '<tr class="fw-detail" data-detail-for="{}" hidden>'
            '<td colspan="{}">'
            '<div class="form-group mb-2">'
            '<label class="small text-muted mb-1">Label</label>'
            '<input type="text" class="form-control form-control-sm" '
            'name="{}_label_{}" value="{}">'
            '</div>'
            '<div class="form-group mb-0">'
            '<label class="small text-muted mb-1">Help Text (HTML allowed)'
            '</label>'
            '<textarea class="form-control form-control-sm" rows="3" '
            'name="{}_help_{}">{}</textarea>'
            '</div>'
            '</td></tr>',
            field_name, columns,
            name, field_name, message.get('label', ''),
            name, field_name, message.get('help_text', ''))

    def render(self, name, value, attrs=None, renderer=None):
        value = value if isinstance(value, dict) else {}
        weights = value.get('weights') or {}
        editable = set(value.get('editable') or [])
        messages = value.get('messages') or {}
        ordered = order_field_names(profile_field_names(), weights)

        rows = []
        for field_name in ordered:
            message = messages.get(field_name) or {}
            rows.append(format_html(
                '<tr draggable="true" data-field="{}"{}>'
                '<td class="fw-grip text-muted">&#9776;</td>'
                '<td class="fw-caret text-muted">&#9656;</td>'
                '<td class="pr-2">{}</td>'
                '<td class="text-center"><input type="checkbox" '
                'name="{}_editable" value="{}"{}></td>'
                '<td><input type="number" step="1" '
                'class="form-control form-control-sm" name="{}_weight_{}" '
                'value="{}"></td>'
                '</tr>',
                field_name,
                mark_safe(' class="fw-configured"') if message else '',
                field_name.replace('_', ' ').title(),
                name, field_name,
                mark_safe(' checked') if field_name in editable else '',
                name, field_name, weights.get(field_name, '')))
            rows.append(self._detail_row(name, field_name, message, 5))

        mechanic_rows = []
        for field_name in SIGNUP_MECHANIC_FIELDS:
            message = messages.get(field_name) or {}
            mechanic_rows.append(format_html(
                '<tr data-field="{}"{}>'
                '<td class="fw-caret text-muted">&#9656;</td>'
                '<td class="pr-2">{}</td></tr>',
                field_name,
                mark_safe(' class="fw-configured"') if message else '',
                field_name.replace('_', ' ').title()))
            mechanic_rows.append(
                self._detail_row(name, field_name, message, 2))

        # The setting page injects this HTML with jQuery .html(), which runs
        # embedded <script> tags — so the drag handlers load with the widget.
        return format_html(
            '<style>'
            'table.field-weights-table tr[draggable] {{ cursor: grab; }}'
            'table.field-weights-table td.fw-grip {{ width: 1.5rem; }}'
            'table.field-weights-table td.fw-caret {{ width: 1.5rem; '
            'cursor: pointer; }}'
            'table.field-weights-table tr.fw-dragging {{ opacity: .4; }}'
            'table.field-weights-table tr.fw-configured td.fw-caret '
            '{{ color: #007bff; font-weight: bold; }}'
            'table.field-weights-table input[type="number"] {{ width: 5rem; }}'
            '</style>'
            '<table class="table table-sm mb-0 field-weights-table">'
            '<thead><tr><th></th><th></th><th>Field</th>'
            '<th class="text-center">Editable</th><th>Weight</th></tr></thead>'
            '<tbody>{}</tbody></table>'
            '<p class="small text-muted mt-3 mb-1">Signup mechanics — wording '
            'only. These fields appear on the application but have no order or '
            'editability.</p>'
            '<table class="table table-sm mb-0 field-weights-table">'
            '<tbody>{}</tbody></table>'
            '<script src="{}"></script>',
            mark_safe(''.join(rows)), mark_safe(''.join(mechanic_rows)),
            static('js/field_weights.js'))


class ProfileFieldsField(forms.Field):
    """Cleans the combined widget payload into
    {'editable': [name, …], 'weights': {name: int},
     'messages': {name: {'label': str, 'help_text': str}}}."""

    widget = ProfileFieldsWidget

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('required', False)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        value = value if isinstance(value, dict) else {}
        weights = {}
        for field_name, raw in (value.get('weights') or {}).items():
            if isinstance(raw, int):
                weights[field_name] = raw
                continue
            try:
                weights[field_name] = int(str(raw).strip())
            except (TypeError, ValueError):
                raise forms.ValidationError(
                    f'Weight for "{field_name}" must be a whole number.')
        editable = list(value.get('editable') or [])
        unknown = [f for f in editable if f not in profile_field_names()]
        if unknown:
            raise forms.ValidationError(
                'Not a profile field: %(fields)s.',
                params={'fields': ', '.join(unknown)})

        messages = {}
        # Hoisted out of the loop: message_fields() rebuilds a list per call.
        allowed = set(message_fields())
        for field_name, entry in (value.get('messages') or {}).items():
            if field_name not in allowed:
                raise forms.ValidationError(
                    'Not a profile field: %(fields)s.',
                    params={'fields': field_name})
            if not isinstance(entry, dict):
                continue
            cleaned_entry = {}
            for key in ('label', 'help_text'):
                text = (entry.get(key) or '').strip()
                if not text:
                    continue
                # Catch a broken {% %} at save time rather than on the
                # student-facing form.
                validate_html_short_code(text)
                cleaned_entry[key] = text
            if cleaned_entry:
                messages[field_name] = cleaned_entry

        return {'editable': editable, 'weights': weights,
                'messages': messages}


class SettingForm(forms.Form):

    profile_fields = ProfileFieldsField(
        label='Profile Fields — Order, Editability, Label & Help Text',
        help_text=mark_safe(
            'Drag a row to reorder, or type a weight and tab out to re-sort; '
            'lower weights render first. Order applies to the student profile '
            'form and to the student application. "Editable" marks the fields '
            'a student may edit once their application status is Accepted — '
            'while Pending every field is editable, and while In Review the '
            'profile is fully locked. '
            'Click a row&rsquo;s caret (&#9656;) to reveal that field&rsquo;s '
            '<strong>Label</strong> and <strong>Help Text</strong>, which '
            'override the wording shown to the student (help text may contain '
            'HTML). A caret shown in colour means that field already has a '
            'label or help text configured. The small table below covers the '
            'signup mechanics (password, confirm password, signature): wording '
            'only, since they have no order or editability.'
        ),
    )

    locked_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        label='Profile Not Editable Message',
        help_text='Shown on the profile page while the application is In Review.',
    )

    editable_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        label='Profile Editable Message',
        help_text='Shown on the profile page when the profile can be edited.',
    )

    profile_review_intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        label='Profile Review Intro.',
        help_text='Shown at the top of the per-term Review Profile modal.',
    )

    profile_review_template = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        validators=[validate_html_short_code],
        label='Profile Review Display Template',
        help_text=(
            'Django template rendered inside the Review Profile modal. The '
            'student object is available as {{ student }} '
            '(e.g. {{ student.user.first_name }}).'
        ),
    )

    profile_display = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        validators=[validate_profile_display],
        label='Student Detail Layout (advanced)',
        help_text=(
            'Raw JSON layout for the staff Student Details panel '
            '(Student.asHTML). A list of rows; each row a list of columns; '
            'each column either "field_path" or {"field": "...", "label": '
            '"..."}. Leave blank to use the default layout. '
            'See available field paths in the documented default.'
        ),
    )

    def _to_python(self):
        """Return dict of form elements from POST."""
        # The combined control edits all three facets; they stay separate flat
        # keys in storage because every consumer reads them independently.
        profile_fields = self.cleaned_data['profile_fields']
        return {
            'field_weights': profile_fields['weights'],
            'editable_fields': profile_fields['editable'],
            'field_messages': profile_fields['messages'],
            'locked_message': self.cleaned_data['locked_message'],
            'editable_message': self.cleaned_data['editable_message'],
            'profile_review_intro': self.cleaned_data['profile_review_intro'],
            'profile_review_template': self.cleaned_data['profile_review_template'],
            'profile_display': self.cleaned_data['profile_display'],
        }


class student_profile(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX') + '_student_profile'

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # `initial` arrives as the stored setting dict (flat keys); fold the
        # three stored keys into the one combined control.
        self.initial['profile_fields'] = {
            'editable': self.initial.get('editable_fields') or [],
            'weights': self.initial.get('field_weights') or {},
            'messages': self.initial.get('field_messages') or {},
        }

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

        available = self.available_display_fields()
        field_list = ', '.join(
            f'{path} ({label})' for path, label in sorted(available.items()))
        base_help = self.fields['profile_display'].help_text
        self.fields['profile_display'].help_text = mark_safe(
            f'{base_help} Available field paths: {field_list}.')

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    @classmethod
    def field_weights(cls):
        """Return the configured {field_name: weight} map ({} when unset, which
        leaves every consuming form in its declared order)."""
        weights = cls.from_db().get('field_weights') or {}
        return weights if isinstance(weights, dict) else {}

    @classmethod
    def field_messages(cls):
        """Return {field_name: {'label': str, 'help_text': str}} for every
        field with configured wording.

        Falls back to the legacy `signup.form_field_messages` JSON blob when
        the new key is absent, so a tenant that has not run the data migration
        keeps its customizations. Never raises: a malformed value yields {},
        because this feeds the student-facing profile form.
        """
        stored = cls.from_db()
        if 'field_messages' in stored:
            messages = stored.get('field_messages')
            return messages if isinstance(messages, dict) else {}

        from cis.settings.signup import signup

        raw = signup.from_db().get('form_field_messages')
        if not raw:
            return {}
        try:
            legacy = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return legacy if isinstance(legacy, dict) else {}

    @classmethod
    def available_display_fields(cls):
        """Return an {field_path: human_label} dict of every field key an admin
        may reference in `profile_display`. Primary source is the
        StudentProfileForm field set (so the two stay in sync); merged with the
        EXTRA_DISPLAY_FIELD_PATHS allowlist of computed model paths the default
        layout uses. Used for validation and to render help text."""
        from cis.forms.student_profile import StudentProfileForm

        available = {}
        for name, field in StudentProfileForm.base_fields.items():
            label = getattr(field, 'label', None) or name.replace('_', ' ').title()
            available[name] = str(label)
        available.update(EXTRA_DISPLAY_FIELD_PATHS)
        return available

    def install(self):
        # Default editable list mirrors the historic post-SIS editable set,
        # which the tenant app owns.
        from cis.forms.student_profile import tenant_editable_fields
        # Preserve any review intro previously configured on the signup setting.
        from cis.settings.signup import signup

        review_intro = (
            signup.from_db().get('student_profile_review_intro')
            or DEFAULT_REVIEW_INTRO
        )

        try:
            legacy_messages = json.loads(
                signup.from_db().get('form_field_messages') or '{}')
        except (TypeError, ValueError):
            legacy_messages = {}
        if not isinstance(legacy_messages, dict):
            legacy_messages = {}

        defaults = {
            'field_weights': default_field_weights(),
            'editable_fields': list(tenant_editable_fields()),
            'field_messages': legacy_messages,
            'locked_message': DEFAULT_LOCKED_MESSAGE,
            'editable_message': DEFAULT_EDITABLE_MESSAGE,
            'profile_review_intro': review_intro,
            'profile_review_template': DEFAULT_REVIEW_TEMPLATE,
            'profile_display': json.dumps(DEFAULT_PROFILE_DISPLAY),
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

    def run_record(self):
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = self._to_python()
        setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
