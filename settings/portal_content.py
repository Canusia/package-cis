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

    homepage_text = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed on home page above roles boxes. <a href="#" class="float-right" onClick="do_bulk_action(\'portal_content\', \'homepage_text\')" >See Preview</a>',
        label="Homepage Text")
    
    demo_request_text = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed on demo request page. <a href="#" class="float-right" onClick="do_bulk_action(\'portal_content\', \'demo_request_text\')" ></a>',
        label="Access Request Page Text")

    student_text = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed above login boxes.  <a href="#" class="float-right" onClick="do_bulk_action(\'portal_content\', \'student_text\')" >See Preview</a>',
        label="Student page Text")
    
    instructor_text = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed above login boxes.  <a href="#" class="float-right" onClick="do_bulk_action(\'portal_content\', \'instructor_text\')" >See Preview</a>',
        label="Instructor page Text")

    instructor_app_text = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at the top of instructor create application.  <a href="#" class="float-right" onClick="do_bulk_action(\'portal_content\', \'instructor_app_text\')" >See Preview</a>',
        label="Instructor start application page Text")

    counselor_text = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed above login boxes.  <a href="#" class="float-right" onClick="do_bulk_action(\'portal_content\', \'counselor_text\')" >See Preview</a>',
        label="Counselor Text")

    faculty_text = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed above login boxes.  <a href="#" class="float-right" onClick="do_bulk_action(\'portal_content\', \'faculty_text\')" >See Preview</a>',
        label="Faculty Page Text")

    staff_text = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed above login boxes.  <a href="#" class="float-right" onClick="do_bulk_action(\'portal_content\', \'staff_text\')" >See Preview</a>',
        label="Staff Page Text")

    student_body = forms.CharField(
        max_length=None, required=False, widget=forms.Textarea,
        help_text='Student landing page body (shortcodes: [breadcrumb] [messages] [login_form] [sso_login] [start_app] [forgot_password]).',
        label="Student page body")
    instructor_body = forms.CharField(
        max_length=None, required=False, widget=forms.Textarea,
        help_text='Instructor landing page body (shortcodes supported).',
        label="Instructor page body")
    faculty_body = forms.CharField(
        max_length=None, required=False, widget=forms.Textarea,
        help_text='Faculty landing page body (shortcodes supported).',
        label="Faculty page body")
    staff_body = forms.CharField(
        max_length=None, required=False, widget=forms.Textarea,
        help_text='College Administrator landing page body (shortcodes supported).',
        label="Staff page body")
    counselor_body = forms.CharField(
        max_length=None, required=False, widget=forms.Textarea,
        help_text='Counselor landing page body (shortcodes supported).',
        label="Counselor page body")


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'homepage_text': self.cleaned_data['homepage_text'],
            'demo_request_text': self.cleaned_data['demo_request_text'],
            'student_text': self.cleaned_data['student_text'],
            'instructor_text': self.cleaned_data['instructor_text'],
            'instructor_app_text': self.cleaned_data['instructor_app_text'],
            'counselor_text': self.cleaned_data['counselor_text'],
            'faculty_text': self.cleaned_data['faculty_text'],
            'staff_text': self.cleaned_data['staff_text'],
            'student_body': self.cleaned_data.get('student_body', ''),
            'instructor_body': self.cleaned_data.get('instructor_body', ''),
            'faculty_body': self.cleaned_data.get('faculty_body', ''),
            'staff_body': self.cleaned_data.get('staff_body', ''),
            'counselor_body': self.cleaned_data.get('counselor_body', ''),
        }


class portal_content(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_page_text"
    
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
        from django.conf import settings

        from cis.models.student import Student
        from cis.forms.student import StudentForm
        from cis.landing_content import render_landing_body
        from cis.forms.customuser import MyCELoginForm

        if field_name in ['homepage_text']:
            # content = self.from_db().get('student_terms')
            template = 'cis/index/index.html'
            return render(
                request,
                template,
                {
                    'portal':settings.MY_CE,
                    'offerings': None,
                    'lookup_form': None
                },
            )
        elif field_name in ['student_text']:
            # content = self.from_db().get('student_terms')
            template = 'cis/index/student.html'
            ctx = {'portal': settings.MY_CE, 'form': MyCELoginForm(request),
                   'registration_is_open': True}
            ctx['page_body'] = render_landing_body(request, 'student', ctx)
            return render(request, template, ctx)
        elif field_name in ['instructor_text']:
            # content = self.from_db().get('student_terms')
            template = 'cis/index/instructor.html'
            ctx = {'portal': settings.MY_CE, 'form': MyCELoginForm(request)}
            ctx['page_body'] = render_landing_body(request, 'instructor', ctx)
            return render(request, template, ctx)
        elif field_name in ['faculty_text']:
            # content = self.from_db().get('student_terms')
            template = 'cis/index/faculty.html'
            ctx = {'portal': settings.MY_CE, 'form': MyCELoginForm(request)}
            ctx['page_body'] = render_landing_body(request, 'faculty', ctx)
            return render(request, template, ctx)
        elif field_name in ['staff_text']:
            # content = self.from_db().get('student_terms')
            template = 'cis/index/staff.html'
            ctx = {'portal': settings.MY_CE, 'form': MyCELoginForm(request)}
            ctx['page_body'] = render_landing_body(request, 'staff', ctx)
            return render(request, template, ctx)
        elif field_name in ['counselor_text']:
            # content = self.from_db().get('student_terms')
            template = 'cis/index/highschool_admin.html'
            ctx = {'portal': settings.MY_CE, 'form': MyCELoginForm(request)}
            ctx['page_body'] = render_landing_body(request, 'counselor', ctx)
            return render(request, template, ctx)
        elif field_name in ['instructor_app_text']:
            from cis.forms.teacher_applicant import TeacherApplicantForm
            # content = self.from_db().get('student_terms')
            template = 'instructor_app/start-app.html'
            return render(
                request,
                template,
                {
                    'form': TeacherApplicantForm()
                },
            )
        
    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        defaults = {'staff_text': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n </div>\r\n </div>\r\n </section>', 'faculty_text': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n </div>\r\n </div>\r\n </section>', 'student_text': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n </div>\r\n </div>\r\n </section>', 'homepage_text': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n\r\n <p class="lead">Please select your role to continue</p>\r\n\r\n </div>\r\n </div>\r\n </section>', 'counselor_text': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n </div>\r\n </div>\r\n </section>', 'instructor_text': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n </div>\r\n </div>\r\n </section>', 'demo_request_text': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n <p class="lead">Please complete this form to submit your request</p>\r\n </div>\r\n </div>\r\n </section>', 'instructor_app_text': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n <p class="lead">Please complete this form to start your application</p>\r\n </div>\r\n </div>\r\n </section>'}

        from cis.landing_content import DEFAULT_BODIES
        for role, body in DEFAULT_BODIES.items():
            defaults[f'{role}_body'] = body

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
