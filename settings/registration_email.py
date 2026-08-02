import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.validators import validate_html_short_code
from ..models.term import Term, AcademicYear
from ..models.settings import Setting

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
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    verify_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Verification Email Subject")

    verification_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent in verification email. Customize with {{student_first_name}}, {{student_last_name}}, {{verification_link}}. <a href="#" class="float-right" onClick="do_bulk_action(\'registration_email\', \'verification_email\')" >See Preview</a>',
        label="Verification Email")

    # new_user_email_subject = forms.CharField(
    #     max_length=200,
    #     help_text='',
    #     label="New Student Welcome Email Subject")

    # new_user_email = forms.CharField(
    #     max_length=None,
    #     widget=forms.Textarea,
    #     validators=[validate_html_short_code],
    #     help_text='Email template sent after new account is created. Customize with {{student_first_name}}, {{student_email}}. <a href="#" class="float-right" onClick="do_bulk_action(\'registration_email\', \'new_user_email_subject\')" >See Preview</a>',
    #     label="New Student Welcome Email")

    # new_counselor_email_subject = forms.CharField(
    #     max_length=200,
    #     help_text='',
    #     label="New High School Counselor Email Subject")

    # new_counselor_email = forms.CharField(
    #     max_length=None,
    #     widget=forms.Textarea,
    #     validators=[validate_html_short_code],
    #     help_text='Customize with {{name}}. Email template sent after new high school name is added by student. <a href="#" class="float-right" onClick="do_bulk_action(\'registration_email\', \'new_counselor_email\')" >See Preview</a>',
    #     label="New High School Counselor Email")

    parent_consent_req_subject = forms.CharField(
        max_length=200,
        help_text='',
        widget=forms.HiddenInput,
        required=False,
        label="Parent Consent Request Email Subject")
        
    parent_consent_req = forms.CharField(
        max_length=None,
        widget=forms.HiddenInput,
        required=False,
        validators=[validate_html_short_code],
        help_text='Must include the following shortcode - {{parent_consent_url}}. Can include {{parent_name}}, {{student_first_name}}, {{student_last_name}}. This email template is used when notifying students with missing parent consent. <a href="#" class="float-right" onClick="do_bulk_action(\'registration_email\', \'parent_consent_req\')" >See Preview</a>',
        label="Parent Consent Request Email")
    
    parent_consent_recv_subject = forms.CharField(
        max_length=200,
        widget=forms.HiddenInput,
        required=False,
        help_text='',
        label="Parent Consent Recv. Email Subject")
        
    parent_consent_recv = forms.CharField(
        max_length=None,
        widget=forms.HiddenInput,
        required=False,
        validators=[validate_html_short_code],
        help_text='Sent to parent and student. <a href="#" class="float-right" onClick="do_bulk_action(\'registration_email\', \'parent_consent_recv\')" >See Preview</a>',
        label="Parent Consent Received Email")

    send_id_assigned_email = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Send an email when ID is assigned?',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))
    
    id_verify_regex = forms.CharField(
        label='Python Regex Pattern to Verify Valid ID',
        help_text='Eg: ^H\\d{5} will match an ID that starts with letter H and is followed by 5 digits'
    )

    id_assigned_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Student ID Assigned Email Subject")
        
    id_assigned_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Sent to student. Customize with {{student_first_name}}, {{student_last_name}}, {{student_id}}. <a href="#" class="float-right" onClick="do_bulk_action(\'registration_email\', \'id_assigned_email\')" >See Preview</a>',
        label="ID Assigned Email Message")
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'is_active': self.cleaned_data['is_active'],

            'verify_email_subject': self.cleaned_data['verify_email_subject'],
            'verification_email': self.cleaned_data['verification_email'],

            # 'new_user_email_subject': self.cleaned_data['new_user_email_subject'],
            # 'new_user_email': self.cleaned_data['new_user_email'],

            'parent_consent_req_subject': self.cleaned_data['parent_consent_req_subject'],
            'parent_consent_req': self.cleaned_data['parent_consent_req'],

            # 'new_counselor_email_subject': self.cleaned_data['new_counselor_email_subject'],
            # 'new_counselor_email': self.cleaned_data['new_counselor_email'],

            'parent_consent_recv_subject': self.cleaned_data['parent_consent_recv_subject'],
            'parent_consent_recv': self.cleaned_data['parent_consent_recv'],

            'send_id_assigned_email': self.cleaned_data['send_id_assigned_email'],
            'id_verify_regex': self.cleaned_data['id_verify_regex'],
            'id_assigned_subject': self.cleaned_data['id_assigned_subject'],
            'id_assigned_email': self.cleaned_data['id_assigned_email']
        }


class registration_email(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_regis_email"
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
        from django.shortcuts import (
            render
        )

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        from cis.models.student import Student
        from cis.forms.student import StudentForm
        from cis.settings.registration_email import registration_email

        email_settings = registration_email.from_db()
        if field_name in ['verification_email' ]:
            subject = email_settings.get('verify_email_subject')
            email = email_settings.get('verification_email')
        if field_name in ['new_user_email_subject' ]:
            subject = email_settings.get('new_user_email_subject')
            email = email_settings.get('new_user_email')
        elif field_name == 'parent_consent_recv':
            subject = email_settings.get('parent_consent_recv_subject')
            email = email_settings.get('parent_consent_recv')
        elif field_name == 'parent_consent_req':
            subject = email_settings.get('parent_consent_req_subject')
            email = email_settings.get('parent_consent_req')
        elif field_name == 'id_assigned_email':
            subject = email_settings.get('id_assigned_subject')
            email = email_settings.get('id_assigned_email')
   
        message = Template(email)
        context = Context({
            'student_first_name': "John",
            'student_email': "john@email.com",
            'student_id': "123456789",
            'course_name': "Course Name",
            'campus': "Campus Name",
            'registration_status': 'Registration Status',
            'parent_consent_url': 'https://custom-url-for-student',
            'verification_link': 'https://custom-url-for-student'
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
        defaults = {
            'verify_email_subject': 'Change Me',
            'verification_email': 'Change Me',

            'is_active': "Change this in Settings -> Students -> Registration Email",
            'new_user_email_subject': 'No',
            'new_user_email': "Change this in Settings -> Students -> Incomplete App Reminder Email",

            'parent_consent_req_subject': "Change this in Settings -> Students -> Incomplete App Reminder Email",
            'parent_consent_req': "Change this in Settings -> Students -> Incomplete App Reminder Email",

            'parent_consent_recv_subject': "Change this in Settings -> Students -> Incomplete App Reminder Email",
            'parent_consent_recv': "Change this in Settings -> Students -> Incomplete App Reminder Email"
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
