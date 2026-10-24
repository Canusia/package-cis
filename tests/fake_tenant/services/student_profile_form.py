"""Stand-in tenant student profile form (package-cis#57).

Its vocabulary is deliberately nobody's: no tenant declares `fake_color`,
`fake_other_color` or `fake_meta_note`, so a test asserting on them cannot pass
because it happens to match the tenant this package was extracted from. The
generic names it does carry (first_name, email, highschool, ethnicity, ...) are
the ones cis code itself reaches for — the importer resolves `highschool` from a
CEEB code, rebinds `ethnicity` and the date fields, CISProfileMixin re-enables
`email` and hides the SSN pair — so a tenant without them is not a shape cis
supports.

Covers every export cis reads from a tenant profile module:

    StudentProfileForm      the field set, with user / student / meta targets,
                            a hidden field and a gated cross-field clean() rule
    EDITABLE_FIELDS         post-SIS editable default, including one name that
                            is not declared (stale entries must be inert)
    NON_IMPORTABLE_FIELDS   a student attestation the importer must drop
    CE_HIDDEN_FIELDS        the same attestation, hidden from the CE form
    StudentCISExtraFields   one CE-only admin field
"""
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from cis.forms.utils import MetaFormMixin, with_meta
from cis.highschool_scope import picker_queryset
from cis.models.customuser import CustomUser
from cis.models.student import Student

FAKE_COLORS = [('', 'Select'), ('red', 'Red'), ('green', 'Green'),
               ('other', 'Something else')]

NON_IMPORTABLE_FIELDS = ('fake_attestation',)

CE_HIDDEN_FIELDS = ('fake_attestation',)

EDITABLE_FIELDS = ('email', 'fake_meta_note', 'fake_not_declared')


class StudentProfileForm(MetaFormMixin, forms.Form):

    first_name = with_meta(
        forms.CharField(label='Fake Given Name', max_length=128),
        target='user')
    last_name = with_meta(
        forms.CharField(label='Fake Family Name', max_length=128),
        target='user')
    email = with_meta(
        forms.EmailField(label='Fake Email', disabled=True),
        target='user')
    password = with_meta(
        forms.CharField(label='Password', max_length=128,
                        widget=forms.PasswordInput),
        target='skip')
    confirm_password = with_meta(
        forms.CharField(label='Retype Password', max_length=128,
                        widget=forms.PasswordInput),
        target='skip')
    date_of_birth = with_meta(
        forms.DateField(label='Fake Birth Date'),
        target='user')
    ssn = with_meta(
        forms.CharField(label='SSN', max_length=15, required=False),
        target='user')
    verify_student_ssn = with_meta(
        forms.CharField(label='Verify SSN', max_length=15, required=False),
        target='skip')
    preferred_name = with_meta(
        forms.CharField(label='Fake Nickname', max_length=50, required=False),
        target='student')
    highschool = with_meta(
        forms.ModelChoiceField(queryset=None, label='Fake School'),
        target='student')
    ethnicity = with_meta(
        forms.MultipleChoiceField(choices=Student.ETHNICITY_OPTIONS,
                                  required=False, label='Fake Heritage',
                                  widget=forms.CheckboxSelectMultiple),
        target='student')
    fake_color = with_meta(
        forms.ChoiceField(choices=FAKE_COLORS, label='Fake Color'),
        target='meta')
    fake_other_color = with_meta(
        forms.CharField(label='Fake Other Color', required=False),
        target='meta')
    fake_meta_note = with_meta(
        forms.CharField(label='Fake Meta Note', required=False),
        target='meta')
    fake_hidden_code = with_meta(
        forms.CharField(required=False, widget=forms.HiddenInput),
        target='meta')
    fake_attestation = with_meta(
        forms.BooleanField(label='Fake Attestation', required=False),
        target='meta')
    signature = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, student=None, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.student = student
        self.request = request

        for name, field in self.fields.items():
            if hasattr(field, 'storage_target') and not getattr(field, 'storage_path', None):
                field.storage_path = name

        self.fields['highschool'].queryset = picker_queryset(
            keep=getattr(student, 'highschool_id', None))

        self._load_field_labels_from_db()
        if student:
            self._populate_initial_from_instance(student)
        self.apply_field_weights()

    def clean(self):
        cleaned_data = super().clean()
        self._sanitize_text_fields()
        # Gated cross-field rule: unless one of the listed colours is chosen,
        # the student must describe theirs. Fires on a blank fake_color too,
        # which is what makes it reach a field the editable form has gated.
        if (cleaned_data.get('fake_color') in (None, '', 'other')
                and not cleaned_data.get('fake_other_color')):
            self.add_error('fake_other_color',
                           'Describe the colour when none of the listed ones fit.')
        return cleaned_data

    def clean_email(self):
        data = (self.cleaned_data.get('email') or '').lower()
        qs = CustomUser.objects.filter(
            Q(email=data) | Q(username=data) | Q(secondary_email=data))
        if self.student:
            qs = qs.exclude(pk=self.student.user_id)
        if qs.exists():
            raise ValidationError('This email is already registered in the system.')
        return data

    def save(self, student=None, commit=True):
        self._sanitize_text_fields()
        student = student or self.student
        if not student:
            raise ValueError('Student instance is required for save')
        user = student.user
        self._save_fields_to_models(user=user, student=student, commit=False)
        if commit:
            user.save()
            student.save()
        return student


class StudentCISExtraFields(forms.Form):
    psid = with_meta(
        forms.CharField(label='Fake Admin Reference', max_length=128,
                        required=False),
        target='user')
