"""Forms for consortiums and a high school's consortium memberships."""
from django import forms
from django.db import IntegrityError, transaction

from cis.models.consortium import Consortium, ConsortiumMembership


class ConsortiumForm(forms.ModelForm):
    """Add / edit a consortium on the /ce/consortiums/ page."""

    class Meta:
        model = Consortium
        fields = ['name', 'description', 'status']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        clash = Consortium.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError('A consortium with this name already exists.')
        return name


class ConsortiumMembershipForm(forms.ModelForm):
    """Add (no ``instance``) or edit (``instance``) a ConsortiumMembership.

    Adding: join an existing Active consortium the school is not already in,
    or name a new one (created on save). Exactly one of the two. Editing: the
    consortium is fixed; only status, joined date and billing basis change.
    """
    new_consortium_name = forms.CharField(
        required=False, max_length=200, label='Or create a new consortium',
        help_text='Name for a new consortium this school starts with.')
    new_consortium_description = forms.CharField(
        required=False, label='New consortium description',
        widget=forms.Textarea(attrs={'rows': 2}))

    class Meta:
        model = ConsortiumMembership
        fields = ['consortium', 'billing_basis', 'joined_on', 'status']
        labels = {
            'billing_basis': 'Billing basis',
            'joined_on': 'Joined on',
        }
        help_texts = {
            'billing_basis': ("How this school's students are billed for a section "
                              "hosted at another member school."),
        }
        widgets = {'joined_on': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, highschool=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.highschool = highschool or getattr(self.instance, 'highschool', None)
        if not self.instance._state.adding:
            for name in ('consortium', 'new_consortium_name', 'new_consortium_description'):
                del self.fields[name]
            return
        joined = self.highschool.consortium_memberships.values_list(
            'consortium_id', flat=True)
        self.fields['consortium'] = forms.ModelChoiceField(
            queryset=Consortium.objects.filter(status='Active')
            .exclude(pk__in=list(joined)).order_by('name'),
            required=False, empty_label='Select a consortium',
            label='Join consortium')
        self.order_fields([
            'consortium', 'new_consortium_name', 'new_consortium_description',
            'billing_basis', 'joined_on', 'status'])

    def clean(self):
        cleaned = super().clean()
        if not self.instance._state.adding:
            return cleaned
        picked = cleaned.get('consortium')
        new_name = (cleaned.get('new_consortium_name') or '').strip()
        cleaned['new_consortium_name'] = new_name
        if picked and new_name:
            raise forms.ValidationError(
                'Pick an existing consortium or name a new one, not both.')
        if not picked and not new_name:
            # Keep a bad pick (e.g. a non-UUID) on its own field error.
            if 'consortium' not in self.errors:
                raise forms.ValidationError(
                    'Pick a consortium to join or name a new one.')
        if new_name and Consortium.objects.filter(name__iexact=new_name).exists():
            self.add_error('new_consortium_name',
                           'A consortium with this name already exists; pick it instead.')
        return cleaned

    def save(self, commit=True):
        membership = super().save(commit=False)
        if self.instance._state.adding:
            membership.highschool = self.highschool
            new_name = self.cleaned_data.get('new_consortium_name')
            if new_name:
                membership.consortium = Consortium.objects.create(
                    name=new_name,
                    description=self.cleaned_data.get('new_consortium_description') or '')
        if commit:
            membership.save()
        return membership

    def save_or_error(self):
        """Save; a lost race on a unique constraint becomes a form error.

        Returns the membership, or None with the error added to the form.
        """
        try:
            with transaction.atomic():
                return self.save()
        except IntegrityError:
            self.add_error(None, 'This high school is already in that consortium, '
                                 'or a consortium with that name was just created.')
            return None
