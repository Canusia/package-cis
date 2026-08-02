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
from cis.validators import validate_html_short_code

class SettingForm(forms.Form):

    subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Incomplete Email Reminder Subject")

    email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template for incomplete reminder, {{student_first_name}}, {{missing_items}}',
        label="Incomplete Email message")

    homeschool_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Homeschool Parent Consent Subject")

    homeschool_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template for home school consent reminder, {{parent_first_name}}, {{parent_last_name}}, {{student_first_name}}, {{student_last_name}}',
        label="Homeschool Consent Request Reminder Email message")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'subject': self.cleaned_data.get('subject'),
            'email': self.cleaned_data.get('email'),
            'homeschool_subject': self.cleaned_data.get('homeschool_subject'),
            'homeschool_email': self.cleaned_data.get('homeschool_email')
        }


class incomplete_student_app_reminder(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_incomplete_student_app"
    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def install(self):
        defaults = {
            'subject': "Test Subject",
            'email': "Test Email"
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

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
