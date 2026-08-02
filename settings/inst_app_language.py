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

class SettingForm(forms.Form):
    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No')
    ]

    is_accepting_new = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Accepting New Applications',
        help_text='Turning this off will stop all emails, and prevent any new or in-progress applications from being submitted. Staff can override status internally on each application',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    closed_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed when no longer accepting applications',
        label="Applications Closed Message")

    dashboard_blurb = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at the top in Dashboard. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'dashboard\')" >See Preview</a>',
        label="Dashboard Intro.")

    course_blurb = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed above course selection drop down. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'courses\')" >See Preview</a>',
        label="Course Description Blurb")

    # number of recommendations needed 0, 1 or 2
    recommendations_needed = forms.IntegerField(
        min_value=0,
        max_value=2
    )

    rec_req_blurb = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at the top of recommendation request page. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'rec_req\')" >See Preview</a>',
        label="Rec. Request Page Intro.")

    rec_req_blurb_bottom = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at the bottom before \'Request Recommendation\' button. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'rec_bottom\')" >See Preview</a>',
        label="Rec. Request Page Intro.")

    rec_req_email_subject = forms.CharField(
        max_length=None,
        help_text='',
        label="Rec. Request Email Subject")

    rec_req_email_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Customize with {{recommender_name}}, {{teacher_first_name}}, {{teacher_last_name}}, {{recommendation_link}}, {{highschool}}, {{course_titles}}. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'rec_req_email_message\')" >See Preview</a>',
        label="Rec. Request Email Message")

    rec_received_email_subject = forms.CharField(
        max_length=None,
        help_text='',
        label="Rec. Received Email Subject")

    rec_received_email_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Customize with {{teacher_first_name}}, {{teacher_last_name}}, {{recommender_name}}. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'rec_received_email_message\')" >See Preview</a>',
        label="Rec. Received Email Message")

    rec_submit_page_header = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at the top of recommendation submission page. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'rec_submit_page_header\')" >See Preview</a>',
        label="Rec. Submit Page Intro")

    rec_submit_page_pre_form = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed after teacher details, and before recommendation form. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'rec_submit_page_header\')" >See Preview</a>',
        label="Rec. Submit Form Intro.")

    ed_bg_page_header = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at the top of Educational Background Page. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'ed_bg_page_header\')" >See Preview</a>',
        label="Educational Background Page Intro")

    file_upload_page_header = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at the top of material upload page. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'file_upload_page_header\')" >See Preview</a>',
        label="Material Upload Page Intro")

    submit_page_header = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at the top of submit page. <a href="#" class="float-right" onClick="do_bulk_action(\'inst_app_language\', \'submit_page_header\')" >See Preview</a>',
        label="Application Submit Page Intro")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'closed_message': self.cleaned_data.get('closed_message'),
            'is_accepting_new': self.cleaned_data.get('is_accepting_new'),
            'recommendations_needed': self.cleaned_data.get('recommendations_needed'),
            
            'dashboard_blurb': self.cleaned_data.get('dashboard_blurb'),
            'course_blurb': self.cleaned_data.get('course_blurb'),
            'rec_req_blurb': self.cleaned_data.get('rec_req_blurb'),
            'rec_req_blurb_bottom': self.cleaned_data.get('rec_req_blurb_bottom'),
            'rec_submit_page_header': self.cleaned_data.get('rec_submit_page_header'),
            'rec_req_email_subject': self.cleaned_data.get('rec_req_email_subject'),            
            'rec_req_email_message': self.cleaned_data.get('rec_req_email_message'),
            'rec_req_email_subject': self.cleaned_data.get('rec_req_email_subject'),
            'rec_received_email_subject': self.cleaned_data.get('rec_received_email_subject'),
            'rec_received_email_message': self.cleaned_data.get('rec_received_email_message'),
            'file_upload_page_header': self.cleaned_data.get('file_upload_page_header'),
            'submit_page_header': self.cleaned_data.get('submit_page_header'),'ed_bg_page_header': self.cleaned_data.get('ed_bg_page_header'),
            'rec_submit_page_pre_form': self.cleaned_data.get('rec_submit_page_pre_form'),
        }

class inst_app_language(SettingForm):
    key = "inst_app_language"

    def preview(self, request, field_name):

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404
        
        from cis.forms.teacher_applicant import (
            TeacherApplicantForm,
            TeacherApplicantProfileForm,
            SchoolCourseForm,
            RecommendationRequestForm,
            RecommondationForm,
            EdBgForm,
            AppUploadForm
        )

        email_settings = self.from_db()

        if field_name in ['dashboard']:
            # content = self.from_db().get('student_terms')
            template = 'instructor_app/dashboard.html'
            return render(
                request,
                template,
                {
                    'intro':self.from_db().get('dashboard_blurb')
                },
            )
        elif field_name in ['file_upload_page_header']:
            return render(
                request,
                'instructor_app/manage_uploads.html',
                {
                    'page_intro': self.from_db().get('file_upload_page_header'),
                }
            )
        elif field_name in ['rec_submit_page_header']:
            return render(
                request,
                'instructor_app/submit_recommendation.html',
                {
                    'page_intro': self.from_db()['rec_submit_page_header'],
                    'pre_form': self.from_db()['rec_submit_page_pre_form'],
                }
            )
        elif field_name in ['submit_page_header']:
            return render(
                request,
                'instructor_app/review_application.html',
                {
                    'menu': None,
                    'page_intro': self.from_db().get('submit_page_header', 'Change in Settings'),
                }
            )
        elif field_name in ['ed_bg_page_header']:
            return render(
                request,
                'instructor_app/manage_ed_bg.html',
                {
                    'menu': None,
                    'page_intro': self.from_db().get('ed_bg_page_header', 'Change in Settings'),
                    'teacher_application': None,
                    'form': None,
                    'ed_bg': None
                }
            )
        elif field_name in ['rec_req', 'rec_bottom']:
            return render(
                request,
                'instructor_app/request_recommendation.html',
                {
                    'menu': None,
                    'page_intro': self.from_db()['rec_req_blurb'],
                    'page_footer': self.from_db()['rec_req_blurb_bottom'],
                    'teacher_application': None,
                    'recommendations': None,
                    'form': None
                }
            )
        if field_name in ['courses']:
            # content = self.from_db().get('student_terms')

            form = SchoolCourseForm(
                teacher_application=None,
                initial={
                    
                    'course_description': self.from_db()['course_blurb']
                }
            )

            template = 'instructor_app/manage_course.html'
            return render(
                request,
                template,
                {
                    'form': form,
                    'teacher_application': None,
                    'interested_courses': None
                },
            )
        if field_name == 'rec_req_email_message':
            email = email_settings.get('rec_req_email_message')
            subject = email_settings.get('course_reviewed_email_subject')
        if field_name == 'rec_received_email_message':
            email = email_settings.get('rec_received_email_message')
            subject = email_settings.get('course_reviewed_email_subject')
        
        email_template = Template(email)
        context = Context({
            'recommender_name': request.user.first_name,
            'teacher_first_name': request.user.first_name,
            'teacher_last_name': request.user.last_name,
            'teacher_email': request.user.email,
            'highschool': 'High School',
            'recommendation_link': 'https://custom-url',
            'course': 'Course',
            'course_titles': 'Course 1 and Course 2',
        })

        text_body = email_template.render(context)
        
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
            'dashboard_blurb': "Change this in Settings -> Instructor -> Application Language",
            'course_blurb': "Change this in Settings -> Instructor -> Application Language",
            'rec_req_blurb': "Change this in Settings -> Instructor -> Application Language",
            'rec_req_blurb_bottom': "Change this in Settings -> Instructor -> Application Language",
            'rec_req_email_subject': "Change this in Settings -> Instructor -> Application Language",
            'rec_req_email_message': "Change this in Settings -> Instructor -> Application Language",
            'rec_received_email_subject': "Change this in Settings -> Instructor -> Application Language",
            'rec_received_email_message': "Change this in Settings -> Instructor -> Application Language",
            'rec_submit_page_header': "Change this in Settings -> Instructor -> Application Language",
            'rec_submit_page_pre_form': "Change this in Settings -> Instructor -> Application Language",
            'ed_bg_page_header': 'Change this in settings'
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
