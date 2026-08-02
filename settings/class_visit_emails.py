# DEPRECATED: This settings class is superseded by class_visit.class_visit.settings.class_visit
# Values are migrated by class_visit migration 0005_migrate_class_visit_emails_settings.
# Do not add new fields here. This file will be removed in a future cleanup.

import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from form_fields import fields as FFields

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..validators import validate_cron, validate_email_list, validate_html_short_code
from ..models.term import Term, AcademicYear
from ..models.settings import Setting

class SettingForm(forms.Form):

    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No'),
        ('Debug', 'Debug'),
    ]

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Email Status',
        help_text='Status of below emails',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'})
    )

    debug_email_list = forms.CharField(
        max_length=200,
        required=False,
        validators=[validate_email_list],
        help_text='Comma separated email list',
        label="If Debug send emails to"
    )

    instructor_visit_scheduled_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Instructor Visit Scheduled Email Subject"
    )

    instructor_visit_scheduled_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='HTML Email template sent to instructor when a visit is scheduled. Customize with {{visit_date}}, {{visitors}}, {{class_sections}}, {{teacher_last_name}}, {{teacher_first_name}}, {{teacher_email}}. <a href="#" class="float-right" onClick="do_bulk_action(\'class_visit_emails\', \'visit_scheduled_instructor\')" >See Preview</a>',
        label="Instructor Visit Scheduled Email"
    )

    visitor_visit_scheduled_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Visit Scheduled Email Subject - Visitors"
    )

    visitor_visit_scheduled_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='HTML Email template sent to visitors when a visit is scheduled. Customize with {{visit_date}}, {{visitors}}, {{pre_visit_note}}, {{class_sections}}, {{teacher_last_name}}, {{teacher_first_name}}, {{teacher_email}}, {{highschool}}. <a href="#" class="float-right" onClick="do_bulk_action(\'class_visit_emails\', \'visit_scheduled_visitor\')" >See Preview</a>',
        validators=[validate_html_short_code],
        label="Visit Scheduled Email - Visitors")

    upload_label = FFields.LongLabelField(
        required=False,
        label='<h3>Visit Report Email Templates</h3>',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    instructor_visit_letter_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Instructor Visit Letter Subject")

    visit_report_submitted_subject = forms.CharField(
        max_length=200,
        help_text='Sent to course administrator(s)',
        label="Visit Report Submitted Email Subject")

    visit_report_submitted_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='HTML Email template sent when a visit report is submitted. Customize with {{report_added_by}}, {{teacher_last_name}}, {{teacher_first_name}}, {{teacher_email}}, {{highschool}}, {{visit_report_url}}. <a href="#" class="float-right" onClick="do_bulk_action(\'class_visit_emails\', \'visit_report_submitted\')" >See Preview</a>',
        label="Visit Report Submitted Email")

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

class class_visit_emails(SettingForm):
    key = str(__name__)

    def preview(self, request, field_name):
        from django.shortcuts import (
            render
        )

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        from cis.models.student import Student
        from cis.forms.student import StudentForm
        from cis.settings.registration_email import registration_email

        email_settings = self.from_db()
        if field_name in ['visit_scheduled_instructor' ]:
            subject = email_settings.get('instructor_visit_scheduled_subject')
            email = email_settings.get('instructor_visit_scheduled_email')
        elif field_name == 'visit_scheduled_visitor':
            subject = email_settings.get('visitor_visit_scheduled_subject')
            email = email_settings.get('visitor_visit_scheduled_email')
        elif field_name == 'visit_report_submitted':
            subject = email_settings.get('visit_report_submitted_subject')
            email = email_settings.get('visit_report_submitted_email')
   
        message = Template(email)
        context = Context({
            'visit_date': "11/18/2018",
            'visitors': "John and Jane",
            'class_sections': "ACC 101",
            'teacher_last_name': "Smith",
            'teacher_first_name': "Dale",
            'teacher_email': "teacher@email.com",
            'pre_visit_note': 'Private Note',
            'highschool': 'High School',
            'report_added_by': 'John Smith',
            'visit_report_url': 'https://custom-url-for-report'
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
