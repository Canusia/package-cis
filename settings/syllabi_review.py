import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy

from ..models.crontab import CronTab

from cis.models.term import AcademicYear, Term
from cis.models.course import Course
from cis.models.teacher import TeacherCourseCertificate

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.settings import Setting
from cis.validators import validate_email_list, validate_cron, validate_html_short_code

from form_fields import fields as FFields

class syllabi_review(forms.Form):

    key = str(__name__)

    mode = forms.ChoiceField(
        choices=(('test', 'Testing'), ('active', 'Active')),
        required=True
    )

    testers = forms.CharField(
        max_length=None,
        validators=[validate_email_list],
        label="Comma separated Test recipients"
    )

    term = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Term(s) for which reminders should be sent'
    )

    starting_date = forms.DateField(label="Email Start Date")
    ending_date = forms.DateField(label="Email End Date (until)")

    cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay',
        label="Cron Expression for emails to instructors pending syllabus, marked as needs update and faculty reminders",
        validators=[validate_cron]
    )

    pending_upload_email_header = FFields.ReadOnlyField(
        required=False,
        label=mark_safe(
            '<h2>Emails to Instructors who have not uploaded syllabus.</h2>'
        ),
        initial='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    missing_syllabus_email_subject = forms.CharField(max_length=500)
    missing_syllabus_email_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Email template sent to instructor when missing class syllabi Short codes supported {{instructor_first_name}}, {{instructor_last_name}}, {{section_list}}, {{term}}. <a href="#" class="float-right" onClick="do_bulk_action(\'syllabi_review\', \'email\')" >See Preview</a>'
    )

    # faculty_email_header = FFields.ReadOnlyField(
    #     required=False,
    #     label=mark_safe(
    #         '<h2>Faculty Email Configuration - Sent to faculty with classes that have pending syllabus review</h2>'
    #     ),
    #     initial='',
    #     widget=FFields.LongLabelWidget(
    #         attrs={
    #             'class':'border-0 bg-light h-100'
    #         }
    #     )
    # )

    # faculty_pending_review_email_subject = forms.CharField(max_length=500)
    # faculty_pending_review_email_message = forms.CharField(
    #     max_length=None,
    #     widget=forms.Textarea,
    #     help_text='Email template sent to Faculty and Visitor when there are class syllabi pending review. Short codes supported {{faculty_first_name}}, {{faculty_last_name}}'
    # )
    
    # portal_headers = FFields.ReadOnlyField(
    #     required=False,
    #     label=mark_safe(
    #         '<h2>Message displayed in instructor and faculty portal page(s)</h2>'
    #     ),
    #     initial='',
    #     widget=FFields.LongLabelWidget(
    #         attrs={
    #             'class':'border-0 bg-light h-100'
    #         }
    #     )
    # )

    # faculty_message = forms.CharField(
    #     max_length=None,
    #     widget=forms.Textarea,
    #     label="Needs Update Note Message",
    #     help_text='This is displayed in the page when faculty marks syllabi as needs update. <a href="#" class="float-right" onClick="do_bulk_action(\'syllabi_review\', \'faculty_message\')" >See Preview</a>'
    # )

    instructor_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        label="Instructor Message",
        help_text='This is displayed to the instructors in their section details page under "Syllabi Tab". Customize with {{note}}. <a href="#" class="float-right" onClick="do_bulk_action(\'syllabi_review\', \'instructor_message\')" >See Preview</a>'
    )

    # teacher_email_header = FFields.ReadOnlyField(
    #     required=False,
    #     label=mark_safe('<h2>Instructor Email Configuration - Sent to instructor after syllabus has been reviewed</h2>'
    #     ),
    #     initial='',
    #     widget=FFields.LongLabelWidget(
    #         attrs={
    #             'class':'border-0 bg-light h-100'
    #         }
    #     )
    # )

    # needs_update_email_subject = forms.CharField(max_length=500)
    # needs_update_email_message = forms.CharField(
    #     max_length=None,
    #     widget=forms.Textarea,
    #     label='Needs Review/Update - Message',
    #     validators=[validate_html_short_code],
    #     help_text='Email template sent to instructor after syllabi is marked as needs update. Short codes supported {{instructor_first_name}}, {{instructor_last_name}}, {{term}}, {{course}}, {{note}}. <a href="#" class="float-right" onClick="do_bulk_action(\'syllabi_review\', \'email_message\')" >See Preview</a>'
    # )

    # reviewed_email_subject = forms.CharField(max_length=500)    
    # email_message_reviewed = forms.CharField(
    #     max_length=None,
    #     widget=forms.Textarea,
    #     label='Approved/Reviewed - Message',
    #     validators=[validate_html_short_code],
    #     help_text='Email template sent to instructor after syllabi is marked as reviewed. Short codes supported {{instructor_first_name}}, {{instructor_last_name}}, {{course_name}}, {{term}}. <a href="#" class="float-right" onClick="do_bulk_action(\'syllabi_review\', \'reviewed_message\')" >See Preview</a>'
    # )

    def clean_term(self):
        data = self.cleaned_data.get('term')

        print(data)
        return [str(d.id) for d in data]

    def clean_starting_date(self):
        data = self.cleaned_data['starting_date']
        return data.strftime('%m/%d/%Y')

    def clean_ending_date(self):
        starting_date = datetime.datetime.strptime(
            self.data.get('starting_date'), '%m/%d/%Y'
        )

        ending_date = datetime.datetime.strptime(
            self.data.get('ending_date'), '%m/%d/%Y'
        )

        if starting_date > ending_date:
            raise ValidationError(
                _(f'End Date has to be after start date.')
            )

        data = self.cleaned_data['ending_date']
        return data.strftime('%m/%d/%Y')

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
        if field_name in ['email' ]:
            subject = email_settings.get('email_subject')
            email = email_settings.get('email_message')
        elif field_name == 'needs_update_email':
            subject = email_settings.get('needs_update_email_subject')
            email = email_settings.get('needs_update_email_message')
        
        message = Template(email)
        context = Context({
            'visit_date': "11/18/2018",
            'visitors': "John and Jane",
            'class_sections': "ACC 101",
            'instructor_last_name': "Smith",
            'instructor_first_name': "Dale",
            'section_list': mark_safe("<br>".join(['ACC 101', 'ACC 102'])),
            'term': "Fall 2020",
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

        self.fields['term'].queryset = Term.objects.all().order_by('-code')

    def install(self):
        defaults = {"mode": "test", "testers": "kadaji@gmail.com", "email_message": "{{instructor_first_name}}, {{instructor_last_name}}, {{section_list}}, {{term}}", "email_subject": "Missing Syllabi", "faculty_message": "note to faculty", "instructor_message": "note to teacher"}

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

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        cron, created = CronTab.objects.get_or_create(
            command='notify_missing_syllabi'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value
        
        return result