import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.crontab import CronTab
from ..models.term import Term, AcademicYear
from ..models.settings import Setting

from ..validators import validate_cron, validate_email_list, validate_html_short_code

class SettingForm(forms.Form):

    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No'),
        ('Debug', 'Debug'),
    ]

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Enabled',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    debug_email_list = forms.CharField(
        max_length=200,
        required=False,
        validators=[validate_email_list],
        help_text='Comma separated email list',
        label="If Debug send emails to")

    pending_rec_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Subject")

    pending_rec_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template must include {{student_list}}. <a href="#" class="float-right" onClick="do_bulk_action(\'school_counselor_regis_email\', \'email\')" >See Preview</a>',
        label="Email")
    
    cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay',
        label="Cron Expression",
        validators=[validate_cron]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        cron, created = CronTab.objects.get_or_create(
            command='notify_school_counselors'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        return {
            'pending_rec_email_subject': self.cleaned_data['pending_rec_email_subject'],
            'debug_email_list': self.cleaned_data.get('debug_email_list'),
            'is_active': self.cleaned_data['is_active'],
            'cron': self.cleaned_data['cron'],
            'pending_rec_email': self.cleaned_data['pending_rec_email']
        }


class school_counselor_regis_email(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_counselor_regis_email"
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

    def preview(self, request, field_name):
        from django.shortcuts import (
            render
        )
        from django.utils.safestring import mark_safe

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        from cis.models.student import Student
        from cis.forms.student import StudentForm
        from cis.settings.student_regis_pending import student_regis_pending

        email_settings = self.from_db()
        if field_name in ['email' ]:
            subject = email_settings.get('pending_rec_email_subject')
            email = email_settings.get('pending_rec_email')

        message = Template(email)
        context = Context({
            'student_first_name': "John",
            'student_last_name': "Smith",
            'student_email': "john@email.com",
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

    def install(self):
        defaults = {'cron': '10 11 * * *', 'pending_rec_email': 'Change this in Settings -> Misc -> Counselor Emails', 'pending_rec_email_subject': 'Change this in Settings -> Misc -> Counselor Emails'}

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
