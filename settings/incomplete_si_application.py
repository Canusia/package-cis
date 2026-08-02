import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..validators import validate_cron, numeric, validate_html_short_code
from ..models.crontab import CronTab
from ..models.term import Term, AcademicYear
from ..models.settings import Setting

class SettingForm(forms.Form):
    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No'),
        ('Debug', 'Debug')
    ]

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Enabled',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    frequency = forms.CharField(
        max_length=2,
        help_text='How often should an instructor be notified',
        label="Frequency",
        validators=[numeric]
    )

    cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay',
        label="Cron Expression",
        validators=[validate_cron]
    )

    email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Email Subject")

    email_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Supports HTML. Customize the message with {{teacher_first_name}}, {{teacher_last_name}}, {{missing_items}}. <a href="#" class="float-right" onClick="do_bulk_action(\'incomplete_si_application\', \'email_message\')" >See Preview</a>',
        label="Email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        cron, created = CronTab.objects.get_or_create(
            command='notify_incomplete_si_app'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        return {
            'is_active': self.cleaned_data['is_active'],
            'cron': self.cleaned_data['cron'],
            'email_subject': self.cleaned_data['email_subject'],
            'frequency': self.cleaned_data['frequency'],
            'email_message': self.cleaned_data['email_message'],
        }


class incomplete_si_application(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_incomplete_is_application"
    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def preview(self, request, field_name):

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        email_settings = self.from_db()

        if field_name == 'email_message':
            email = email_settings.get('email_message')
            subject = email_settings.get('email_subject')
        
        email_template = Template(email)
        context = Context({
            'teacher_first_name': request.user.first_name,
            'teacher_last_name': request.user.last_name,
            'missing_items': [
                'Select interested course(s)',
                'Waiting for recommendation letter',
                'Missing Education Background',
                'Upload supporting materials'
            ],
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

    def install(self):
        defaults = {
            'is_active': "Debug",
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
