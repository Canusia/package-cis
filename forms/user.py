# custom user form
from django import forms
from django.core.exceptions import ValidationError

from django.conf import settings
from ..models.section import Campus

class UserForm(forms.Form):
    """
    User Form
    """
    first_name = forms.CharField(
        label='First Name',
        max_length=128,
        widget=forms.TextInput(attrs={'class': 'col-md-6 col-sm-12'}))

    last_name = forms.CharField(
        label='Last Name',
        max_length=128,
        widget=forms.TextInput(attrs={'class': 'col-md-8 col-sm-12'}))

    email = forms.EmailField(
        label='Campus Email',
        widget=forms.TextInput(attrs={'class': 'col-md-9 col-sm-12'}))

    username = forms.CharField(
        label='Username',
        widget=forms.TextInput(attrs={'class': 'col-md-9 col-sm-12'}))

    password = forms.CharField(
        label='Password',
        required=False,
        widget=forms.TextInput(attrs={'class': 'col-md-9 col-sm-12'}))

    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No')
    ]

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Account Enabled',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    manage_settings = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Update Settings',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    manage_staff_accounts = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Manage Staff User Accounts',
        help_text='Should this user be able to add/edit new EC staff accounts?',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    process_campus = forms.MultipleChoiceField(
        choices=(),
        required=False,
        label='Campus(es) User can Edit',
        widget=forms.CheckboxSelectMultiple()
    )

    default_campus = forms.ChoiceField(
        choices=(),
        label='Default Campus',
        required=False
    )

    def __init__(self, *args, user=None, record=None, **kwargs):
        """``user`` is the staff member filling in the form: they may only
        grant the campuses they can edit themselves (superusers, and callers
        passing no user, see every campus). ``record`` is the staff member
        being edited, whose campuses outside that set are kept, not dropped."""
        super().__init__(*args, **kwargs)

        from cis.campus_gate import get_accessible_campuses
        if user is not None:
            campus = get_accessible_campuses(user)
        else:
            campus = Campus.objects.filter(
                code__startswith=settings.CAMPUS_CODE_PREFIX).all()
        editable = {str(obj.id) for obj in campus}

        self.fields['process_campus'].choices = [
            (obj.id, obj.name) for obj in campus
        ]

        # Campuses the record has that the editor can't grant or revoke.
        self._kept_campuses = []
        default_choices = [(obj.id, obj.name) for obj in campus]
        if record is not None:
            from cis.signals.staff_campus import process_campus_ids
            self._kept_campuses = [
                pk for pk in process_campus_ids(record) if pk not in editable]

            default = (record.campus or {}).get('default_campus')
            if default and default not in editable:
                current = Campus.objects.filter(pk=default).first()
                if current:
                    default_choices.append((current.id, current.name))

        self.fields['default_campus'].choices = default_choices

    def clean_process_campus(self):
        return list(self.cleaned_data['process_campus']) + self._kept_campuses
