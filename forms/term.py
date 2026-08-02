from django import forms
from django.utils.translation import gettext_lazy as _
from django.forms import ValidationError

from cis.utils import get_foreign_key_references
from cis.models.term import (
    Term, AcademicYear
)

class AcademicYearUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )


class TermUploadForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'accept': 'text/csv'})
    )


class MigrateAcademicYearForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_academic_year'
    )

    destination_record = forms.ModelChoiceField(
        required=True,
        queryset=None,
        label='Destination Record'
    )

    move_items = forms.MultipleChoiceField(
        label='Select Items to Move',
        choices=[
            ('registrations', 'Registrations'),
            ('support_docs', 'Support Docs.'),
            ('student_agreements', 'Student Agreements'),
            ('student_recommendation', 'Recommendations'),
            ('parent_consent', 'Parent Consent'),
            ('notes', 'Notes'),
        ],
        widget=forms.CheckboxSelectMultiple
    )

    confirm = forms.BooleanField(
        required=True,
        label='I understand this action cannot be undone.'
    )
    
    # class Media:
    #     js = [
    #         'js/student_migration.js'
    #     ]

    def __init__(self, record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['destination_record'].queryset = AcademicYear.objects.all().exclude(
            id=record.id
        )

        references = get_foreign_key_references(record)
        move_item_choices = []

        for model_name, obj in references:
            choice = (f"{model_name}", f"{model_name}")
            if choice not in move_item_choices:
                move_item_choices.append(choice)

        self.fields['move_items'].choices = move_item_choices

    def save(self, request, record):
        data = self.cleaned_data
        references = get_foreign_key_references(record)

        success, message = True, []
        for model_name, obj in references:

            if model_name in data.get('move_items'):
                try:
                    obj.academic_year = data.get('destination_record')
                    obj.save()

                    message.append(
                        f'Successfully moved {model_name} - {obj}'
                    )
                except Exception as e:
                    success = False
                    message.append(
                        f'Failed to move {model_name} - {obj} {e}. Please edit/delete this record manually'
                    )

        return (success, message)

class MigrateTermForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_term'
    )

    destination_record = forms.ModelChoiceField(
        required=True,
        queryset=None,
        label='Destination Record'
    )

    move_items = forms.MultipleChoiceField(
        label='Select Items to Move',
        choices=[
            ('registrations', 'Registrations'),
            ('support_docs', 'Support Docs.'),
            ('student_agreements', 'Student Agreements'),
            ('student_recommendation', 'Recommendations'),
            ('parent_consent', 'Parent Consent'),
            ('notes', 'Notes'),
        ],
        widget=forms.CheckboxSelectMultiple
    )

    confirm = forms.BooleanField(
        required=True,
        label='I understand this action cannot be undone.'
    )
    
    # class Media:
    #     js = [
    #         'js/student_migration.js'
    #     ]

    def __init__(self, record, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['destination_record'].queryset = Term.objects.all().exclude(
            id=record.id
        )

        references = get_foreign_key_references(record)
        move_item_choices = []

        for model_name, obj in references:
            choice = (f"{model_name}", f"{model_name}")
            if choice not in move_item_choices:
                move_item_choices.append(choice)

        self.fields['move_items'].choices = move_item_choices

    def save(self, request, record):
        data = self.cleaned_data
        references = get_foreign_key_references(record)

        success, message = True, []
        for model_name, obj in references:

            if model_name in data.get('move_items'):
                try:
                    obj.term = data.get('destination_record')
                    obj.save()

                    message.append(
                        f'Successfully moved {model_name} - {obj}'
                    )
                except Exception as e:
                    success = False
                    message.append(
                        f'Failed to move {model_name} - {obj} {e}. Please edit/delete this record manually'
                    )

        return (success, message)

class AcademicYearForm(forms.ModelForm):
    """
    Academic Year Form
    """
    hs_start_date = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y'),
        label="HS Start Date",
        required=False
    )

    hs_end_date = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y'),
        label="HS End Date",
        required=False
    )

    class Meta:
        model = AcademicYear
        fields = '__all__'
        exclude = [
            'cost_per_credit',
            'temp_id',
            'meta'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['hs_start_date'].required = True
        self.fields['hs_end_date'].required = True
        
    def clean_hs_start_date(self):
        data = self.cleaned_data['hs_start_date']
        return data

    def clean_hs_end_date(self):
        """
        Check to ensure end date is after start date, if not
        raises ValidationError
        """
        start_date = self.cleaned_data['hs_start_date']
        end_date = self.cleaned_data['hs_end_date']

        if end_date < start_date:
            raise ValidationError(
                _("Enter a valid end date in the future"),
                code='invalid')
        return end_date

class BulkAssignParentForm(forms.Form):
    parent = forms.ModelChoiceField(
        required=True, label='Parent Term',
        queryset=Term.objects.select_related('academic_year').order_by(
            '-academic_year__name', '-code'),
    )

    def __init__(self, ids=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ids = [str(i) for i in (ids or [])]
        if self.ids:
            self.fields['parent'].queryset = self.fields['parent'].queryset.exclude(
                pk__in=self.ids)

    def save(self):
        parent = self.cleaned_data['parent']
        assigned, skipped = 0, 0
        for term in Term.objects.filter(pk__in=self.ids):
            if term.pk == parent.pk or term.would_create_cycle(parent):
                skipped += 1
                continue
            term.parent = parent
            term.save(update_fields=['parent'])
            assigned += 1
        return assigned, skipped


class TermForm(forms.ModelForm):

    # payment_due_date = forms.DateField(
    #     widget=forms.DateInput(format='%m/%d/%Y'),
    #     label="Payment Due Date",
    #     help_text='This is not the sequence class payment due date'
    # )

    class Meta:
        model = Term
        fields = '__all__'

        exclude = [
            'temp_id',
            'dates',
            'meta'
        ]
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        qs = Term.objects.select_related('academic_year').order_by(
            '-academic_year__name', '-code')
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields['parent'].queryset = qs
        self.fields['parent'].required = False

    def clean_parent(self):
        parent = self.cleaned_data.get('parent')
        if parent is None:
            return parent
        if self.instance and self.instance.pk:
            if parent.pk == self.instance.pk:
                raise ValidationError('A term cannot be its own parent.')
            if self.instance.would_create_cycle(parent):
                raise ValidationError(
                    'That parent would create a circular term hierarchy.')
        return parent

    def save(self, commit=False):
        record = super().save(commit=False)
        data = self.cleaned_data

        dates = record.dates if record.dates else {}
        # dates['payment_due_date'] = data.get('payment_due_date').strftime('%m/%d/%Y')
        
        record.dates = dates
        if commit:
            record.save()

        return record