"""Headless per-row validation for the student CSV importer.

Built on the tenant's StudentProfileForm to inherit its field validators
(email format, DOB range, graduation-date future, phone formatting, SSN), while:
  * taking no request (so address-API validation is skipped),
  * resolving the high school from a CEEB code, scoped to an allowed queryset,
  * dropping the password/confirm/ssn-verify mechanic fields (system password),
  * NOT failing on an already-registered email (the importer reports that as a
    'duplicate' outcome instead),
  * binding single-cell CSV values for date/multi-choice widgets,
  * accepting the values counselors' own SIS exports produce
    (package-highschool_admin#20): common date layouts, yes/no cells in any
    case or as y/n, true/false, 1/0, and a blank optional yes/no cell as "No".

The class is assembled per tenant by student_import_row_form() rather than
subclassed at import time (#57), so a changed TENANT_SERVICES_APP reaches it.
`from cis.forms.student_import import StudentImportRowForm` keeps working
through the module __getattr__ at the bottom, resolved when the import runs.
"""
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from cis.forms import student_profile as _profile
from cis.models.highschool import HighSchool
from cis.highschool_scope import picker_queryset
from cis.models.student import Student
from cis.services.importers.validation import (
    DEFAULT_DATE_INPUT_FORMATS, NO_WORDS, YES_WORDS, coerce_yes_no,
    has_two_digit_year, import_date_input_formats)


class DelimitedMultipleChoiceField(forms.MultipleChoiceField):
    """MultipleChoiceField that accepts a single pipe-delimited CSV cell."""

    def to_python(self, value):
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        return [v.strip() for v in str(value).split('|') if v.strip()]


# YES_WORDS / NO_WORDS and the date helpers live in
# cis.services.importers.validation (#114 item 10) so the pydantic row schemas
# share them; the names stay importable from here.

_DATE_DIRECTIVES = (('%Y', 'YYYY'), ('%m', 'MM'), ('%d', 'DD'))


def _is_plain_choice_field(field):
    return (isinstance(field, forms.ChoiceField)
            and not isinstance(field, (forms.MultipleChoiceField,
                                       forms.ModelChoiceField)))


def _flat_choices(field):
    """(value, label) pairs as strings, optgroups flattened."""
    out = []
    for value, label in field.choices:
        if isinstance(label, (list, tuple)):
            out.extend((str(v), str(l)) for v, l in label)
        else:
            out.append((str(value), str(label)))
    return out


def _yes_no_values(field):
    """(yes_value, no_value, is_binary) for a plain ChoiceField, matching on
    the choice value or its label — cis.utils.YES_NO_OPTIONS stores 1/2 under
    Yes/No labels, tenants' IEP/504 store 'Yes'/'No'. is_binary is True only
    when Yes and No are the field's sole non-blank choices."""
    if not _is_plain_choice_field(field):
        return None, None, False
    yes = no = None
    nonblank = [(v, l) for v, l in _flat_choices(field) if v != '']
    for value, label in nonblank:
        keys = {value.strip().casefold(), label.strip().casefold()}
        if 'yes' in keys and yes is None:
            yes = value
        elif 'no' in keys and no is None:
            no = value
    binary = yes is not None and no is not None and len(nonblank) == 2
    return yes, no, binary


class StudentImportRowMixin:
    """The importer's behaviour on top of a tenant StudentProfileForm. Must
    precede the tenant form in the MRO; see student_import_row_form()."""

    # Accepted date layouts (strptime). %m/%d also accept unpadded digits, so
    # '%m/%d/%Y' covers both MM/DD/YYYY and M/D/YYYY. A deployment may replace
    # the list with settings.STUDENT_IMPORT_DATE_INPUT_FORMATS (student import
    # only) or the generic settings.IMPORT_DATE_INPUT_FORMATS. Two-digit
    # years are always rejected: '5/2/11' has no safe century for a birth date.
    DATE_INPUT_FORMATS = DEFAULT_DATE_INPUT_FORMATS
    DATE_FIELDS = ('date_of_birth', 'start_date', 'graduation_date')

    # Optional Yes/No columns whose blank cell is stored as "No", so a
    # counselor can fill in only the yeses. Opt-in per field: cis cannot know
    # whether a tenant's blank means "No" or "not reported" (self-
    # identification, attestations), and recording a "No" nobody gave is the
    # worse mistake. Tenants list theirs as IMPORT_BLANK_AS_NO_FIELDS in their
    # student_profile_form module (see tenant_import_blank_as_no_fields());
    # a subclass may extend this tuple. Required fields are never defaulted.
    BLANK_AS_NO_FIELDS = ()

    # Generic account mechanics only. Anything tenant-specific comes from
    # tenant_non_importable_fields() — 'cte' used to sit in this tuple and is an
    # ewu field, so a tenant that does not collect it carried a dead name while a
    # tenant with its own such fields had nowhere to put them.
    DROP_FIELDS = ('password', 'confirm_password', 'verify_student_ssn', 'signature')

    def __init__(self, *args, highschools=None, **kwargs):
        self._allowed_highschools = (
            highschools if highschools is not None
            else picker_queryset()
        )
        super().__init__(student=None, request=None, *args, **kwargs)
        self._date_formats = self.date_input_formats()

        # Resolved per instance, not at import time: the accessor reaches into
        # the tenant app, which imports cis.models at module level. Called
        # through the module (not a from-import) so the schema below and this
        # form share one patch point and cannot be stubbed apart.
        for name in self.DROP_FIELDS + _profile.tenant_non_importable_fields():
            self.fields.pop(name, None)

        # email arrives from CSV, so the field must accept bound data
        if 'email' in self.fields:
            self.fields['email'].disabled = False

        # high school is resolved from CEEB in clean_highschool(); make the
        # base ModelChoiceField non-required so an empty PK doesn't short-circuit
        # before our resolver runs, and scope the queryset to the allowed set.
        self.fields['highschool'].required = False
        self.fields['highschool'].queryset = self._allowed_highschools

        # default mailing == permanent unless the row explicitly says otherwise
        if 'same_as_permanent' in self.fields:
            self.fields['same_as_permanent'].initial = True

        # single-cell date binding (base form uses SelectDateWidget/date input)
        invalid_date = 'Enter a real date as %s.' % self._message_formats_phrase()
        for name in self.DATE_FIELDS:
            if name in self.fields:
                field = self.fields[name]
                field.widget = forms.DateInput()
                field.input_formats = list(self._date_formats)
                field.error_messages = dict(field.error_messages,
                                            invalid=invalid_date)
                field.to_python = self._reject_two_digit_year(field.to_python)

        # single-cell multi-choice binding for ethnicity.
        #
        # The replacement must inherit the storage metadata of the field it
        # replaces. MetaFormMixin._save_fields_to_models keys off
        # storage_target, so a field built fresh here is skipped by the save
        # loop: the row validates, the import reports success, and the value is
        # silently discarded (ewu#39). getattr defaults keep a tenant whose
        # ethnicity field carries no metadata behaving as before.
        if 'ethnicity' in self.fields:
            replaced = self.fields['ethnicity']
            field = DelimitedMultipleChoiceField(
                choices=Student.ETHNICITY_OPTIONS, required=False,
            )
            field.storage_target = getattr(replaced, 'storage_target', None)
            field.storage_path = getattr(replaced, 'storage_path', None)
            self.fields['ethnicity'] = field

        if self.is_bound:
            self.data = self._normalized_data(self.data)

    # ---- value normalization (package-highschool_admin#20) ----------------

    @classmethod
    def date_input_formats(cls):
        return tuple(getattr(settings, 'STUDENT_IMPORT_DATE_INPUT_FORMATS', None)
                     or import_date_input_formats(cls.DATE_INPUT_FORMATS))

    @classmethod
    def accepted_date_formats(cls):
        """Human-readable layouts, e.g. ['MM/DD/YYYY', 'M/D/YYYY', ...]."""
        shown = []
        for fmt in cls.date_input_formats():
            text = fmt
            for directive, word in _DATE_DIRECTIVES:
                text = text.replace(directive, word)
            shown.append(text)
            # Month/day-first layouts are where unpadded digits are common.
            if not fmt.startswith('%Y'):
                shown.append(text.replace('MM', 'M').replace('DD', 'D'))
        return shown

    def _formats_phrase(self):
        return ', '.join(self.accepted_date_formats())

    def _message_formats_phrase(self):
        # For ValidationError messages, which Django (and tenant fields that
        # re-raise with params) %-format: a directive left untranslated by a
        # settings override ('%b') would otherwise raise ValueError while the
        # errors render.
        return self._formats_phrase().replace('%', '%%')

    def _reject_two_digit_year(self, to_python):
        message = ('Use a four-digit year. Accepted formats: %s.'
                   % self._message_formats_phrase())

        def wrapped(value):
            if has_two_digit_year(value):
                raise ValidationError(message, code='invalid')
            return to_python(value)
        return wrapped

    def _blank_defaults_to_no(self, name, field):
        if field.required:
            return False
        return name in (tuple(self.BLANK_AS_NO_FIELDS)
                        + _profile.tenant_import_blank_as_no_fields())

    def _normalized_data(self, data):
        """A copy of the bound data with yes/no, boolean and choice cells
        mapped onto the field's own values. Never mutates the caller's data
        (the importer stores raw_data as uploaded)."""
        data = data.copy()
        for name, field in self.fields.items():
            if isinstance(field, forms.BooleanField):
                try:
                    answer = coerce_yes_no(data.get(name) or '')
                except ValueError:
                    answer = None
                if answer is not None:
                    data[name] = 'true' if answer else 'false'
                continue
            if not _is_plain_choice_field(field):
                continue
            raw = data.get(name)
            raw = '' if raw is None else str(raw).strip()
            yes, no, binary = _yes_no_values(field)
            if raw == '':
                if binary and self._blank_defaults_to_no(name, field):
                    data[name] = no
                elif name in data:
                    data[name] = ''
                continue
            data[name] = self._match_choice(field, raw, yes, no)
        return data

    @staticmethod
    def _match_choice(field, raw, yes, no):
        choices = _flat_choices(field)
        if any(raw == value for value, _ in choices):
            return raw
        folded = raw.casefold()
        for value, label in choices:
            if folded in (value.casefold(), label.strip().casefold()):
                return value
        if yes is not None and no is not None:
            if folded in YES_WORDS:
                return yes
            if folded in NO_WORDS:
                return no
        return raw

    @classmethod
    def column_notes(cls):
        """{column: note} describing the accepted values, generated from the
        row form so upload pages need not hardcode format rules."""
        form = cls()
        notes = {}
        for name, field in form.fields.items():
            if isinstance(field, forms.DateField):
                notes[name] = 'Date as %s (four-digit year).' % form._formats_phrase()
            elif isinstance(field, forms.BooleanField):
                notes[name] = 'Yes or No (also Y/N, True/False, 1/0); blank = No.'
            elif isinstance(field, DelimitedMultipleChoiceField):
                notes[name] = 'Separate multiple values with |.'
            else:
                yes, no, binary = _yes_no_values(field)
                if yes is None or no is None:
                    continue
                note = 'Yes or No (also Y/N, True/False, 1/0)'
                if binary and form._blank_defaults_to_no(name, field):
                    note += '; blank = No'
                notes[name] = note + '.'
        return notes

    def clean_highschool(self):
        ceeb = (self.data.get('highschool_ceeb') or '').strip()
        if not ceeb:
            raise ValidationError('High school CEEB code is required.')
        hs = self._allowed_highschools.filter(code=ceeb).first()
        if hs is None:
            raise ValidationError(
                'No high school you can assign matches CEEB code "%s".' % ceeb
            )
        return hs

    def clean_email(self):
        # Normalize only. Existence/duplicate handling belongs to the importer.
        return (self.cleaned_data.get('email') or '').lower()


class StudentImportUploadForm(forms.Form):
    file = forms.FileField(widget=forms.FileInput(attrs={'accept': 'text/csv'}))


# --------------------------------------------------------------------------
# Lazy resolution
# --------------------------------------------------------------------------

# Keyed by the tenant base class, so one class object per tenant form: callers
# subclass it and isinstance-check it, and Django caches form media per class.
_row_form_cache = {}


def student_import_row_form():
    """StudentImportRowForm for the current tenant's StudentProfileForm."""
    base = _profile.StudentProfileForm
    cls = _row_form_cache.get(base)
    if cls is None:
        cls = type('StudentImportRowForm', (StudentImportRowMixin, base),
                   {'__module__': __name__})
        _row_form_cache[base] = cls
    return cls


def __getattr__(name):
    if name == 'StudentImportRowForm':
        return student_import_row_form()
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
