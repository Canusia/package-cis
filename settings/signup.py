import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from cis.validators import validate_html_short_code, validate_json
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.settings import Setting

class SettingForm(forms.Form):

    # Profile-form labels/help text now live on the student_profile setting
    # (field_messages), configured per field alongside order and editability.
    # This map is for the email-verify StudentForm and stays here.
    verify_form_field_messages = forms.CharField(
        max_length=None,
        validators=[validate_json],
        widget=forms.Textarea,
        help_text='Verify Form Field Labels & Help Text',
        label="Student Verify Email Form Field Labels")

    email_verify_intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at top of Start Application Page - BEFORE email is verified',
        label="Pre-Email Verify Page Intro.")
    
    awaiting_verify_intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at top of Awaiting Verification Page',
        label="Awaiting Verification Page Intro.")

    confirm_verify_intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at top of Confirm Verification Page',
        label="Confirm Verification Page Intro.")
    
    intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at top of Start Application Page - AFTER email is verified. <a href="#" class="float-right" onClick="do_bulk_action(\'signup\', \'intro\')" >See Preview</a>',
        label="Post Email Verify Page Intro.")

    signup_terms = forms.CharField(
        max_length=None,
        required=False,
        widget=forms.HiddenInput,
        help_text='Terms to agree in Signup Page. <a href="#" class="float-right" onClick="do_bulk_action(\'signup\', \'signup_terms\')" >See Preview</a>',
        label="Terms")

    student_terms = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Student Agreement Terms. Use {{highschool_name}} <a href="#" class="float-right" onClick="do_bulk_action(\'signup\', \'student_terms\')" >See Preview</a>',
        label="Agreement Terms")

    error_messages = forms.CharField(
        max_length=None,
        validators=[validate_json],
        widget=forms.Textarea,
        help_text='Valid JSON',
        label="Alert/Error Messages")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'email_verify_intro': self.cleaned_data['email_verify_intro'],
            'awaiting_verify_intro': self.cleaned_data['awaiting_verify_intro'],
            'confirm_verify_intro': self.cleaned_data['confirm_verify_intro'],
            'intro': self.cleaned_data['intro'],
            'error_messages': self.cleaned_data['error_messages'],
            'verify_form_field_messages': self.cleaned_data['verify_form_field_messages'],
            'signup_terms': self.cleaned_data['signup_terms'],
            'student_terms': self.cleaned_data['student_terms'],
        }


class signup(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_signup"
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

        from cis.models.student import Student
        from cis.forms.student import StudentForm

        if field_name in ['intro', 'signup_terms' ]:
            signup_intro = Student.get_student_signup_intro()
            form = StudentForm(request)
    
            template = 'student/start_app.html'
            return render(
                request,
                template,
                {
                    'is_registration_open': True,
                    'form': form,
                    'signup_intro': signup_intro
                },
            )
        elif field_name == 'student_terms':
            template = 'cis/print_base.html'
            content = self.from_db().get('student_terms')
            
            return render(
                request,
                template, 
                {
                    'main_content': content
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
        defaults = {'email_verify_intro': 'Change Me', 'awaiting_verify_intro': '', 'intro': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n<p class="alert alert-info">Please complete the form to start your application</p>\r\n </div>\r\n </div>\r\n </section>', 'signup_terms': 'Change this in Settings -> Students -> Signup Page', 'student_terms': 'Change this in Settings -> Students -> Signup Page', 'error_message': '{"start_app": {"success": "Please check your email for further instructions","error": "Unable to create application. The administrator has been notified.","form_validation_fail": "Unable to complete request. Please correct the error(s) and try again","dup_email": {"non_student_account_exists": "An account with this email already exists. Unable to create a student account. Please contact our office for further assistance","account_unverified": "An account with this email already exists. An verification link has been emailed to this address. Please see that email for further instructions","being_processed": "An account with this email already exists. We will contact you once your application has been processed","pending_ernie_login": "An account with this email already exists. Please login with your Ernie credentials"}' + '},"verify_email": {"invalid_token": "The verification token is not associated with the student. Please contact our office for further assistance","account_already_verified": "Your email has already been verified. Please contact our office for further assistance","success": "Your email has been successfully verified. Please continue"},"complete_signup": {"awaiting_processing_error": "Your application is currently being processed. Please contact our office for further assistance","error": "Unable to create application. The administrator has been notified.","success": "We have received your application. You will receive an email once you are ready to register for classes.","form_validation_fail": "Unable to complete request. Please correct the error(s) and try again"}' + '}'}

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
