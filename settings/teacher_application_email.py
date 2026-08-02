import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from form_fields import fields as FFields

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.settings import Setting
from ..validators import validate_cron, validate_email_list, validate_html_short_code

class SettingForm(forms.Form):

    new_applicant_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="New Applicant Welcome Email Subject")

    new_applicant_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent after new account is created. Customize with {{first_name}}, {{last_name}}, {{email}}. <a href="#" class="float-right" onClick="do_bulk_action(\'teacher_application_email\', \'new_applicant_email\')" >See Preview</a>',
        label="New Applicant Welcome Email")

    course_selected_email_recipient = forms.CharField(
        max_length=200,
        help_text='Send emails to this address when course is added, application is submitted',
        label="Email Recipient (Internal)",
        validators=[validate_email_list]
    )

    course_selected_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Course Selected Email Subject")

    course_selected_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent when a course is added to the application. Customize with {{teacher_first_name}}, {{teacher_last_name}}, {{teacher_email}}, {{course}}, {{highschool}}, {{application_url}}. <a href="#" class="float-right" onClick="do_bulk_action(\'teacher_application_email\', \'course_selected_email\')" >See Preview</a>',
        label="Course selected Email")

    app_submitted_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Application Submitted Email Subject")

    app_submitted_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent when an application status is changed to \'Submitted\'. Customize with {{teacher_first_name}}, {{teacher_last_name}}, {{teacher_email}}, {{highschool}}, {{courses}}. <a href="#" class="float-right" onClick="do_bulk_action(\'teacher_application_email\', \'app_submitted_email\')" >See Preview</a>',
        label="Application Submitted Email")

    app_decision_made_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Application Decision Made Internal Email Subject")

    app_decision_made_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent when an application status is changed to \'Decision Made\'. Customize with {{teacher_first_name}}, {{teacher_last_name}}, {{teacher_email}}, {{highschool}}, {{courses}}. <a href="#" class="float-right" onClick="do_bulk_action(\'teacher_application_email\', \'app_decision_made_email\')" >See Preview</a>',
        label="Application Decision Made Email")

    ready_for_review_subsection = FFields.LongLabelField(
        required=False,
        label='',
        initial='Email FC(s) when added as Reviewer',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'h-100 border-0',
                'style': 'padding-left: 0; font-size: 1.3em;'
            }
        )
    )


    reviewer_notif_cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay. This controls when the reviwers will receive the email',
        label="Cron Expression",
        validators=[validate_cron]
    )

    fc_ready_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Ready for Faculty Review - Subject")

    fc_ready_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template for the email digest sent when there is an application is ready for review. Customize with {{applicants_list}}, {{fc_first_name}}, {{fc_last_name}}. <a href="#" class="float-right" onClick="do_bulk_action(\'teacher_application_email\', \'fc_ready_email\')" >See Preview</a>',
        label="Application Ready for Review Email")

    course_reviewed_subsection = FFields.LongLabelField(
        required=False,
        label='',
        initial='After a Faculty reviews.',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'h-100 border-0',
                'style': 'padding-left: 0; font-size: 1.3em;'
            }
        )
    )

    course_reviewed_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="FC Course Status Updated")

    course_reviewed_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent when a FC reviews a course. Customize with {{teacher_first_name}}, {{teacher_last_name}}, {{teacher_email}}, {{highschool}}, {{application_url}}, {{course}}, {{course_review_status}}, {{reviewer_name}}. <a href="#" class="float-right" onClick="do_bulk_action(\'teacher_application_email\', \'course_reviewed_email\')" >See Preview</a>',
        label="FC Course Status Updated Email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'new_applicant_email_subject': self.cleaned_data['new_applicant_email_subject'],
            'new_applicant_email': self.cleaned_data['new_applicant_email'],
            'course_selected_email_recipient': self.cleaned_data['course_selected_email_recipient'],
            'course_selected_email_subject': self.cleaned_data['course_selected_email_subject'],
            'course_selected_email': self.cleaned_data['course_selected_email'],
            
            'fc_ready_email_subject': self.cleaned_data['fc_ready_email_subject'],
            'fc_ready_email': self.cleaned_data['fc_ready_email'],
            
            'app_submitted_email_subject': self.cleaned_data['app_submitted_email_subject'],
            'app_decision_made_email_subject': self.cleaned_data['app_decision_made_email_subject'],
            'app_submitted_email': self.cleaned_data['app_submitted_email'],
            'app_decision_made_email': self.cleaned_data['app_decision_made_email'],
            'course_reviewed_email_subject': self.cleaned_data['course_reviewed_email_subject'],
            'course_reviewed_email': self.cleaned_data['course_reviewed_email'],
        }


class teacher_application_email(SettingForm):
    key = "tapp_email"
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

        if field_name == 'course_reviewed_email':
            email = email_settings.get('course_reviewed_email')
            subject = email_settings.get('course_reviewed_email_subject')
        if field_name == 'fc_ready_email':
            email = email_settings.get('fc_ready_email')
            subject = email_settings.get('course_reviewed_email_subject')
        if field_name == 'app_decision_made_email':
            email = email_settings.get('app_decision_made_email')
            subject = email_settings.get('course_reviewed_email_subject')
        if field_name == 'app_submitted_email':
            email = email_settings.get('app_submitted_email')
            subject = email_settings.get('course_reviewed_email_subject')
        if field_name == 'course_selected_email':
            email = email_settings.get('course_selected_email')
            subject = email_settings.get('course_reviewed_email_subject')
        if field_name == 'new_applicant_email':
            email = email_settings.get('new_applicant_email')
            subject = email_settings.get('course_reviewed_email_subject')
        
        email_template = Template(email)
        context = Context({
            'applicants_list': '<br>'.join([
                'Name 1', 'Name 2'
            ]),
            'fc_first_name': request.user.first_name,
            'fc_last_name': request.user.last_name,
            'first_name': request.user.first_name,
            'email': request.user.email,
            'last_name': request.user.last_name,
            'teacher_first_name': request.user.first_name,
            'teacher_last_name': request.user.last_name,
            'teacher_email': request.user.email,
            'highschool': 'High School',
            'application_url': 'https://custom-url',
            'course': 'Course',
            'courses': 'Course 1 and Course 2',
            'course_review_status': 'Approved',
            'reviewer_name': 'Reviewer Name'
        })

        text_body = email_template.render(context)
        
        return render(
            request,
            'cis/email.html',
            {
                'message': text_body
            }
        )

    def install(self):
        defaults = {
            'new_applicant_email_subject': "Change this in Settings -> Teacher -> Application Email(s)",
            'new_applicant_email': "Change this in Settings -> Teacher -> Application Email(s)",
            'course_selected_email_recipient': "kadaji@gmail.com",
            'course_selectedemail_subject': "Change this in Settings -> Teacher -> Application Email(s)",
            'course_selected_email': "Change this in Settings -> Teacher -> Application Email(s)",
            'app_submitted_email_subject': "Change this in Settings -> Teacher -> Application Email(s)",
            'app_submitted_email': "Change this in Settings -> Teacher -> Application Email(s)",
            'course_reviewed_email_subject': "Change this in Settings -> Teacher -> Application Email(s)",
            'course_reviewed_email': "Change this in Settings -> Teacher -> Application Email(s)",
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
