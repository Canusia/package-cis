from django import forms
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from cis.models.district import (
    District, DistrictPosition,
    DistrictAdministrator, DistrictAdministratorPosition)

from cis.utils import user_has_cis_role, get_foreign_key_references

class MigrateForm(forms.Form):
    
    action = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial='migrate_district'
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

        self.fields['destination_record'].queryset = District.objects.all().exclude(
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
                    obj.district = data.get('destination_record')
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

class DistrictAdministratorPositionForm(forms.Form):
    district = forms.ModelChoiceField(queryset=District.objects.all().order_by('name'))
    position = forms.ModelChoiceField(queryset=DistrictPosition.objects.all().order_by('name'))
    status = forms.ChoiceField(choices=DistrictAdministratorPosition.STATUS_OPTIONS)
    district_admin = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    id = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )
    ajax = forms.CharField(
        required=True,
        widget=forms.HiddenInput
    )

class DistrictAdministratorForm(forms.Form):
    first_name = forms.CharField(label='First Name', max_length=128)
    last_name = forms.CharField(label='Last Name', max_length=128)
    email = forms.EmailField(label='Primary Email')

    def clean_email(self):
        data = self.cleaned_data['email']
        return data.lower()

class DistrictPositionForm(ModelForm):
    class Meta:
        model = DistrictPosition
        fields = '__all__'

class DistrictForm(ModelForm):
    class Meta:
        model = District
        fields = '__all__'

    def save(self, commit=True):
        instance = super(DistrictForm, self).save(commit=False)
        if commit:
            instance.save()
        return instance

    def clean_name(self):
        """
        Checks to ensure District Name is not empty
        """
        data = self.cleaned_data['name'].strip()

        if data == '':
            raise ValidationError(_("District name cannot be empty"), code="invalid")
        return data
