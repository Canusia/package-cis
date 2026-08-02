"""Headless per-row validation for the student CSV importer.

Subclasses StudentProfileForm to inherit its field validators (email format,
DOB range, graduation-date future, phone formatting, SSN), while:
  * taking no request (so address-API validation is skipped),
  * resolving the high school from a CEEB code, scoped to an allowed queryset,
  * dropping the password/confirm/ssn-verify mechanic fields (system password),
  * NOT failing on an already-registered email (the importer reports that as a
    'duplicate' outcome instead),
  * binding single-cell CSV values for date/multi-choice widgets.
"""
from django import forms
from django.core.exceptions import ValidationError

from cis.forms.student_profile import StudentProfileForm
from cis.models.highschool import HighSchool
from cis.models.student import Student


class DelimitedMultipleChoiceField(forms.MultipleChoiceField):
    """MultipleChoiceField that accepts a single pipe-delimited CSV cell."""

    def to_python(self, value):
        if not value:
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        return [v.strip() for v in str(value).split('|') if v.strip()]


class StudentImportRowForm(StudentProfileForm):

    DROP_FIELDS = ('password', 'confirm_password', 'verify_student_ssn', 'signature', 'cte')

    def __init__(self, *args, highschools=None, **kwargs):
        self._allowed_highschools = (
            highschools if highschools is not None
            else HighSchool.objects.filter(status__iexact='Active')
        )
        super().__init__(student=None, request=None, *args, **kwargs)

        for name in self.DROP_FIELDS:
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
        for name in ('date_of_birth', 'start_date', 'graduation_date'):
            if name in self.fields:
                self.fields[name].widget = forms.DateInput()
                self.fields[name].input_formats = ['%m/%d/%Y', '%Y-%m-%d']

        # single-cell multi-choice binding for ethnicity
        if 'ethnicity' in self.fields:
            self.fields['ethnicity'] = DelimitedMultipleChoiceField(
                choices=Student.ETHNICITY_OPTIONS, required=False,
            )

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
