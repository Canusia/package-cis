import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.settings import Setting

from ..validators import numeric, validate_11_number

class SettingForm(forms.Form):

    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No')
    ]

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Enabled',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'})
    )

    footer = forms.CharField(
        max_length=100,
        widget=forms.Textarea,
        required=False,
        help_text='Limit of 100 characters, this will be added to all SMS going out from the system',
        label="SMS Footer")
    
    from_phone = forms.IntegerField(
        help_text='Valid 11 digit Twilio Phone Number. The configuration also requires valid TWILIO SID and AuthToken. Please provide that to the administrators separately.',
        label="Valid Twilio Phone #",
        # min_length=11,
        # max_length=11
        # validators=[numeric, validate_11_number]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'is_active': self.cleaned_data['is_active'],
            'footer': self.cleaned_data.get('footer', ''),
            'from_phone': self.cleaned_data['from_phone'],
        }


class sms(SettingForm):
    key = str(__name__)

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        defaults = {
            'is_active': 'No',
            'footer': 'Change me in Settings -> Misc -> SMS',
            'from_phone': '19282186718'
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

    def run_record(self):
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = self._to_python()
        setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
