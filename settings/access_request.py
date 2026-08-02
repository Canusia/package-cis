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
from cis.validators import validate_html_short_code, validate_email_list

class SettingForm(forms.Form):
    submitted_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Request Submitted - Email Subject")

    submitted_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent to approved request. Customize with {{name}}, {{highschool}}, {{highschool_country}}. <a href="#" class="float-right" onClick="do_bulk_action(\'access_request\', \'approved_email\')" >See Preview</a>',
        label="Request Submitted - Email"
    )
    
    submitted_internal_notification = forms.CharField(
        max_length=200,
        validators=[validate_email_list],
        help_text='Who should be notified when a request has been submitted. Internal Users Only. Comma separated for multiple addresses',
        label="Request Submitted - Notification List")

    approved_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Access Approved - Email Subject")

    approved_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent to approved request. Customize with {{name}}, {{password_reset_link}}. <a href="#" class="float-right" onClick="do_bulk_action(\'access_request\', \'approved_email\')" >See Preview</a>',
        label="Access Approved - Email"
    )

    denied_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Access Denied - Email Subject")

    denied_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent to denied request. Customize with {{name}}. <a href="#" class="float-right" onClick="do_bulk_action(\'access_request\', \'denied_email\')" >See Preview</a>',
        label="Access Denied - Email"
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

class access_request(SettingForm):
    key = str(__name__)

    def preview(self, request, field_name):
        from django.shortcuts import (
            render
        )
        from django.utils.safestring import mark_safe

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        from cis.models.student import Student
        from cis.settings.student_regis_pending import student_regis_pending

        email_settings = self.from_db()
        if field_name in ['approved_email' ]:
            subject = email_settings.get('approved_subject')
            email = email_settings.get('approved_email')
        elif field_name in ['denied_email' ]:
            subject = email_settings.get('denied_subject')
            email = email_settings.get('denied_email')

        message = Template(email)
        context = Context({
            'name': "John Smith",
            'student_last_name': "Smith",
            'password_reset_link': "https://some-unique-url.edu",
            'student_list': mark_safe("<br>".join({'Student 1', 'Student 2', 'Student 3'})),
        })
        
        text_body = message.render(context)
        
        return render(
            request,
            'cis/email.html',
            {
                'message': text_body
            }
        )

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
            'approved_subject': "Change Me",
            'approved_email': "Change Me",
            'denied_email': "Change Me",
            'denied_subject': "Change Me",
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
