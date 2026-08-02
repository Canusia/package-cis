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
        help_text='Report ready email subject.  <a href="#" class="float-right" onClick="do_bulk_action(\'reports_email\', \'subject\')" >See Preview</a>',
        label="Email Subject")

    email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template when report is ready. Customize with {{report_download_url}}, {{first_name}}, {{report_title}}.  <a href="#" class="float-right" onClick="do_bulk_action(\'reports_email\', \'email\')" >See Preview</a>',
        label="Email"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value

        return result

class reports_email(SettingForm):
    # key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_reports_email"
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

    def install(self):
        defaults = {'email': '<p style=\'font-size: 16px; line-height: 24px\'>Dear {{first_name}},</p>\r\n\r\n<p style=\'font-size: 16px; line-height: 24px\'>Your requested report for {{report_title}} is ready for download at <br><a href="{{report_download_url}}">{{report_download_url}}</a></p>', 'subject': 'Report is ready for download'}

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()


    def preview(self, request, field_name):

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        email_settings = self.from_db()

        email = email_settings.get('email')
        subject = email_settings.get('subject')

        email_template = Template(email)
        context = Context({
            'first_name': request.user.first_name,
            'report_download_url': "https://report-download-url",
            'report_title': 'Report Title'
        })

        text_body = email_template.render(context)
        
        return render(
            request,
            'cis/email.html',
            {
                'message': text_body
            }
        )

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
