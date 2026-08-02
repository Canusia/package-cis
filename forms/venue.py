from django import forms
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from cis.models.event import (
    Venue
)

class VenueForm(ModelForm):
    class Meta:
        model = Venue
        fields = '__all__'

    def save(self, commit=True):
        instance = super(VenueForm, self).save(commit=False)
        if commit:
            instance.save()
        return instance

    def clean_name(self):
        """
        Checks to ensure Venue Name is not empty
        """
        data = self.cleaned_data['name'].strip()

        if data == '':
            raise ValidationError(_("Name cannot be empty"), code="invalid")
        return data
