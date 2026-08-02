from django import forms
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.course import Cohort
from cis.models.event import Event, Speaker


class EventCohortExpenseForm(forms.Form):
    event = forms.CharField(
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

    item_type = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial="cohort expense"
    )
    cost = forms.CharField(
        widget=forms.TextInput(attrs={'class':'col-md-5', 'placeholder':'0.00'})
    )
    note = forms.CharField(required=False, widget=forms.Textarea)
    
    def __init__(self, *args, **kwargs):
        super(EventCohortExpenseForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_class = 'event_item_frm'
        self.helper.form_method = 'GET'

        self.helper.add_input(Submit('submit', 'Save'))

class EventCISExpenseForm(forms.Form):
    event = forms.CharField(
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

    item_type = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial="cis expense"
    )
    cost = forms.CharField(
        widget=forms.TextInput(attrs={'class':'col-md-5', 'placeholder':'0.00'})
    )
    note = forms.CharField(required=False, widget=forms.Textarea)
    
    def __init__(self, *args, **kwargs):
        super(EventCISExpenseForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_class = 'event_item_frm'
        self.helper.form_method = 'GET'

        self.helper.add_input(Submit('submit', 'Save'))

class EventCopyReqForm(forms.Form):
    event = forms.CharField(
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
    ordered_on = forms.DateField(
        widget=forms.DateInput(attrs={'class':'col-md-6 col-sm-12'})
    )
    completed_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class':'col-md-6 col-sm-12'}))

    item_type = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial="copies"
    )
    cost = forms.CharField(
        widget=forms.TextInput(attrs={'class':'col-md-5', 'placeholder':'0.00'})
    )
    note = forms.CharField(required=False, widget=forms.Textarea)

    def clean_ordered_on(self):
        data = self.cleaned_data['ordered_on']
        return data.strftime("%m/%d/%Y")

    def clean_completed_on(self):
        data = self.cleaned_data['completed_on']
        if data:
            return data.strftime("%m/%d/%Y")
        return data
    
    def __init__(self, *args, **kwargs):
        super(EventCopyReqForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_class = 'event_item_frm'
        self.helper.form_method = 'GET'

        self.helper.add_input(Submit('submit', 'Save'))

class EventRefreshmentForm(forms.Form):
    event = forms.CharField(
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
    item_type = forms.CharField(
        required=True,
        widget=forms.HiddenInput,
        initial="refreshment"
    )
    ordered_on = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class':'col-md-6 col-sm-12'}),
        input_formats=[('%m/%d/%Y')]
    )
    confirmed_on = forms.DateField(
        required=False,
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class':'col-md-6 col-sm-12'}),
        input_formats=[('%m/%d/%Y')])
    caterer = forms.CharField()
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class':'col-md-6'}))
    delivery_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'class':'col-md-4'})
    )
    cost = forms.CharField(
        widget=forms.TextInput(attrs={'class':'col-md-5', 'placeholder':'0.00'})
    )
    note = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super(EventRefreshmentForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_class = 'event_item_frm'
        self.helper.form_method = 'GET'

        self.helper.add_input(Submit('submit', 'Save'))

    def clean_ordered_on(self):
        data = self.cleaned_data['ordered_on']
        return data.strftime("%m/%d/%Y")

    def clean_confirmed_on(self):
        data = self.cleaned_data['confirmed_on']
        if data:
            return data.strftime("%m/%d/%Y")
        return data

class EventCohortForm(forms.Form):
    cohort = forms.ModelChoiceField(queryset=Cohort.objects.all())

    event = forms.CharField(
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

class EventSpeakerForm(forms.Form):
    speaker = forms.ModelChoiceField(queryset=Speaker.objects.all())

    event = forms.CharField(
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

class EventForm(ModelForm):
   
    class Meta:
        model = Event
        fields = ['name', 'venue', 'start_time', 'end_time', 'type', 'term_tbd']

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

    def clean_end_time(self):
        data = self.cleaned_data['end_time']

        if data < self.cleaned_data['start_time']:
            raise ValidationError(_("Enter an end time after start time"))
        return data
