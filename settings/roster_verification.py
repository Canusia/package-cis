"""Roster Verification settings (key: cis.settings.roster_verification).

Change log
----------
0.1.13a (2026-10-06) -- package-cis#69
  * "Who can verify a class roster?" (`verifiers`): the instructor and/or
    high school admins. A setting saved before this has no `verifiers` key
    and keeps the old behaviour, instructor only; use get_verifiers() /
    can_verify(), never the raw key.
  * High school admins whose role has "Verify Class Rosters" set to Yes get
    the verification request and reminders, through their own subject and
    message (`hsadmin_request_verify_subject` / `hsadmin_request_verify_email`).
    Sections with no instructor are now notified when admins can verify.
  * The confirmation email goes to whoever reported the roster (instructor
    or high school admin); a CE change still confirms to the instructor.
    New short codes: {{reporter_first_name}}, {{reporter_last_name}}, and
    {{recipient_first_name}}, {{recipient_last_name}} in the request emails.
  * The confirmation and staff emails honour Debug mode like the request
    email; they previously keyed off Django's DEBUG and a fixed address.
"""
import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from form_fields import fields as FFields

from ..models.crontab import CronTab
from ..models.term import Term, AcademicYear
from ..models.section import ClassSection
from ..models.settings import Setting

from ..validators import validate_cron, validate_email_list, validate_html_short_code

VERIFIER_CHOICES = (
    ('instructor', 'Instructor'),
    ('highschool_admin', 'High School Admin(s)'),
)
DEFAULT_VERIFIERS = ['instructor']


class SettingForm(forms.Form):

    mode = forms.ChoiceField(
        choices=(('debug', 'Debug'), ('active', 'Active'), ('inactive', 'Inactive'),),
        required=True
    )

    notify_address = forms.CharField(
        help_text='Comma separated list of (staff/testers) email addresses for debug mode, and also for notifying when roster status is changed',
        label="Notification List",
        validators=[validate_email_list]
    )

    intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at the top in Instructor roster verification page. <a href="#" class="float-right" onClick="do_bulk_action(\'roster_verification\', \'intro\')" >See Preview</a>',
        label="Intro.")

    verifiers = forms.MultipleChoiceField(
        choices=VERIFIER_CHOICES,
        initial=DEFAULT_VERIFIERS,
        widget=forms.CheckboxSelectMultiple,
        label='Who can verify a class roster?',
        help_text=(
            'High school admins also need "Verify Class Rosters" set to Yes on '
            'their role at the section\'s high school.'
        ),
    )


    pending_veri_group = FFields.LongLabelField(
        required=False,
        label=mark_safe('<h4>Repeated Notifications when sections are in Pending Verification</h4>'),
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    frequency = forms.CharField(
        max_length=2,
        help_text='How often should an instructor with a \'pending verification\' class status be notified',
        label="Frequency of Notification in days"
    )

    cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay',
        label="When should the notification be sent?",
        validators=[validate_cron]
    )

    request_verify_subject = forms.CharField(
        max_length=None,
        help_text='Customize with {{class_number}}, {{section_number}}, {{course_name}}, {{term}}',
        label="Verification Request Email Subject")

    request_verify_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Customize with {{teacher_first_name}}, {{teacher_last_name}}, {{class_number}}, {{section_number}}, {{course_name}}, {{highschool}}, {{term}}. <a href="#" class="float-right" onClick="do_bulk_action(\'roster_verification\', \'request_verify_email\')" >See Preview</a>',
        label="Verification Request Email Message")

    hsadmin_request_verify_subject = forms.CharField(
        max_length=None,
        required=False,
        help_text='Sent to high school admins when they can verify. Customize with {{class_number}}, {{section_number}}, {{course_name}}, {{term}}',
        label="Verification Request Email Subject (High School Admins)")

    hsadmin_request_verify_email = forms.CharField(
        max_length=None,
        required=False,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Customize with {{recipient_first_name}}, {{recipient_last_name}}, {{teacher_first_name}}, {{teacher_last_name}}, {{class_number}}, {{section_number}}, {{course_name}}, {{highschool}}, {{term}}. <a href="#" class="float-right" onClick="do_bulk_action(\'roster_verification\', \'hsadmin_request_verify_email\')" >See Preview</a>',
        label="Verification Request Email Message (High School Admins)")
   
    action_veri_group = FFields.LongLabelField(
        required=False,
        label=mark_safe('<h4 class="mt-5">Notifications after roster has been reviewed</h4>'),
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    verify_confirmation_subject = forms.CharField(
        max_length=None,
        help_text='',
        label="Verification Recv. Confirmation Email Subject (sent to whoever reported)")

    verify_confirmation_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Customize with {{reporter_first_name}}, {{reporter_last_name}}, {{teacher_first_name}}, {{teacher_last_name}}, {{crn}}, {{highschool}}, {{course_name}}, {{section_number}}, {{term}}, {{roster_status}}. <a href="#" class="float-right" onClick="do_bulk_action(\'roster_verification\', \'verify_confirmation_email\')" >See Preview</a>',
        label="Verification Recv. Email Message (sent to whoever reported)")

    ce_veri_group = FFields.LongLabelField(
        required=False,
        label=mark_safe('<h4 class="mt-5">Staff Notifications</h4>'),
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    notify_status = forms.MultipleChoiceField(
        choices=ClassSection.ROSTER_STATUS,
        help_text='when should CE office be notified',
        label="Status to Notify",
        required=False
    )

    notify_verify_confirmation_subject = forms.CharField(
        max_length=None,
        help_text='',
        label="Class Roster Changed Email Subject")

    notify_verify_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Customize with {{teacher_first_name}}, {{teacher_last_name}}, {{crn}}, {{highschool}}, {{course_name}}, {{section_number}}, {{term}}, {{roster_status}}, {{note}}. <a href="#" class="float-right" onClick="do_bulk_action(\'roster_verification\', \'notify_verified_email\')" >See Preview</a>',
        label="Class Roster Changed Email Message")
   
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if 'highschool_admin' in (cleaned.get('verifiers') or []):
            for name in ('hsadmin_request_verify_subject', 'hsadmin_request_verify_email'):
                if not cleaned.get(name):
                    self.add_error(
                        name, 'Required when high school admins can verify rosters.')
        return cleaned

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        cron, created = CronTab.objects.get_or_create(
            command='notify_rosters_pending_verification'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value
        
        return result

class roster_verification(SettingForm):
    key = str(__name__)

    def preview(self, request, field_name):
        from django.shortcuts import (
            render
        )

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        from cis.settings.registration_email import registration_email
        from cis.settings.instructor_portal import instructor_portal as portal_lang

        email_settings = self.from_db()

        if field_name in ['intro']:
            grade_settings = self.from_db()
            
            return render(
                request,
                'instructor/class_section.html',
                {
                    'menu': None,
                    'intro': portal_lang(request).from_db().get('classes_blurb', 'Change me'),
                    'class_section': None,
                    'students_in_class': None,
                    'syllabi': None,
                    'verify_roster_form': None,
                    'intro': portal_lang(request).from_db().get('class_blurb', 'Change me'),
                    'schedule_form': None,
                    'notes': [],
                    'roster_intro': grade_settings.get('intro'),
                    'syllabi_form': None
                })

        if field_name in ['request_verify_email' ]:
            subject = email_settings.get('request_verify_subject')
            email = email_settings.get('request_verify_email')
        elif field_name == 'hsadmin_request_verify_email':
            subject = email_settings.get('hsadmin_request_verify_subject')
            email = email_settings.get('hsadmin_request_verify_email')
        elif field_name == 'verify_confirmation_email':
            subject = email_settings.get('verify_confirmation_subject')
            email = email_settings.get('verify_confirmation_email')
        elif field_name == 'notify_verified_email':
            subject = email_settings.get('notify_verify_confirmation_subject')
            email = email_settings.get('notify_verify_email')
        
        message = Template(email)
        context = Context({
            'visit_date': "11/18/2018",
            'crn': "12345",
            'highschool': "John J High School",
            'course_name': "ACC 101",
            'section_number': "v001",
            'roster_status': "Accurate or Not Accurate",
            'note': "Missing application from Mary, Hutch should be in a different section",
            'class_sections': "ACC 101",
            'teacher_last_name': "Smith",
            'teacher_first_name': "Dale",
            'recipient_first_name': "Pat",
            'recipient_last_name': "Jones",
            'reporter_first_name': "Pat",
            'reporter_last_name': "Jones",
            'class_number': "12345",
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

    def install(self):
        defaults = {
            'cron': '10 11 * * *',
            'intro': 'in instructor portal',
            'frequency': '3',
            'notify_status': ['accurate', 'inaccurate'],
            'notify_address': 'kadaji@gmail.com',
            'notify_verify_email': '{{teacher_first_name}}, {{teacher_last_name}}, {{crn}}, {{highschool}}, {{course_name}}, {{section_number}}, {{term}}, {{roster_status}}, {{note}}',
            'request_verify_email': '{{teacher_first_name}}, {{teacher_last_name}}, {{crn}}, {{highschool}}, {{course_name}}, {{section_number}}, {{term}}', 
            'request_verify_subject': 'Requesting verification', 
            'verify_confirmation_email': '{{teacher_first_name}}, {{teacher_last_name}}, {{crn}}, {{highschool}}, {{course_name}}, {{section_number}}, {{term}}, {{roster_status}}', 'verify_confirmation_subject': 'verified', 
            'notify_verify_confirmation_subject': 'roster status changed',
            'verifiers': list(DEFAULT_VERIFIERS),
            'hsadmin_request_verify_subject': 'Requesting roster verification',
            'hsadmin_request_verify_email': '{{recipient_first_name}}, please verify the roster for {{course_name}} {{section_number}} ({{class_number}}) at {{highschool}}, {{term}}. Instructor: {{teacher_first_name}} {{teacher_last_name}}',
        }

        Setting.install_defaults(self.key, defaults)

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


def get_verifiers(values=None):
    """Roles that may verify a roster: a subset of 'instructor' and
    'highschool_admin'. A setting saved before #69 has no `verifiers` key and
    means instructor only -- read it through here, not from the raw dict."""
    if values is None:
        values = roster_verification.from_db()
    allowed = dict(VERIFIER_CHOICES)
    verifiers = [v for v in (values.get('verifiers') or []) if v in allowed]
    return verifiers or list(DEFAULT_VERIFIERS)


def can_verify(role, values=None):
    """True if `role` ('instructor' or 'highschool_admin') may verify rosters."""
    return role in get_verifiers(values)
