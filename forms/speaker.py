from django import forms
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

class SpeakerForm(forms.Form):
    first_name = forms.CharField(label='First Name', max_length=128)
    last_name = forms.CharField(label='Last Name', max_length=128)
    email = forms.EmailField(label='Primary Email')
