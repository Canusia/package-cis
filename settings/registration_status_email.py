import hashlib
import json
import re
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cis.validators import validate_html_short_code, validate_email_list, validate_cron

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.section import StudentRegistration
from ..models.settings import Setting

from django.utils.safestring import mark_safe
from form_fields import fields as FFields

SIS_ERROR_KINDS = [
    ('registration', 'Registration failure'),
    ('eligibility', 'Eligibility block'),
]


def sis_error_key(message):
    """Stable key for a SIS error message: same text whatever its spacing or case."""
    text = re.sub(r'\s+', ' ', (message or '').strip()).casefold()
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def record_sis_mirror_errors(kind, messages):
    """Add each message not seen before to the setting's sis_mirror_known_errors.

    Returns (first message the admin ticked to stop mirroring, or None;
    messages added by this call). Runs under the current campus (the mirror
    runs inside the registration's campus), and locks the setting row so
    concurrent runs and an admin saving the page don't lose each other's change.
    """
    messages = [m.strip() for m in messages if (m or '').strip()]
    if not messages:
        return None, []
    key = registration_status_email.key
    with transaction.atomic():
        setting = Setting.objects.select_for_update().filter(key=key).first()
        if setting is None:
            setting = Setting(key=key, value={})
        value = dict(setting.value or {})
        # non-dict entries are dropped on write
        known = [e for e in (value.get('sis_mirror_known_errors') or []) if isinstance(e, dict)]
        known_keys = {e.get('key') for e in known}
        stop_keys = set(value.get('sis_mirror_stop_on_errors') or [])

        stop_message, new = None, []
        for message in messages:
            k = sis_error_key(message)
            if k not in known_keys:
                known.append({'key': k, 'message': message, 'kind': kind,
                              'first_seen': timezone.now().isoformat()})
                known_keys.add(k)
                new.append(message)
            elif stop_message is None and k in stop_keys:
                stop_message = message
        if new:
            value['sis_mirror_known_errors'] = known
            setting.value = value
            setting.save()
    return stop_message, new


class SettingForm(forms.Form):
    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No')
    ]

    sis_mirror_trigger = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        label='SIS Mirror Trigger(s)',
        help_text='Status when \'needs mirror\' to SIS should be turned on',
        widget=forms.CheckboxSelectMultiple
    )
    
    sis_mirror_terms = forms.MultipleChoiceField(
        required=False,
        label='SIS Mirror Term(s)',
        help_text='Only registrations in these terms are sent to the SIS by the scheduled '
                  'mirror. Leave all unticked to mirror every term. A parent term includes '
                  'its sub-terms.',
        widget=forms.CheckboxSelectMultiple
    )

    sis_mirror_stop_on_errors = forms.MultipleChoiceField(
        required=False,
        label='Stop mirroring when these errors happen again',
        help_text='Every SIS error that blocks a registration from mirroring is added here '
                  'automatically, and the SIS Mirror Notification Email(s) are told. Tick an '
                  'error to take a registration out of the mirror queue the next time it fails '
                  'with it; staff re-queue it (Set needs mirroring) once the cause is fixed. '
                  'Unticked errors keep retrying on every run.',
        widget=forms.CheckboxSelectMultiple
    )

    cron = forms.CharField(
        max_length=50,
        help_text='Min Hr Day Month WeekDay',
        label="Cron Expression for Mirroring with SIS",
        validators=[validate_cron]
    )

    sis_mirror_error_notifications = forms.CharField(
        max_length=200,
        validators=[validate_email_list],
        help_text='Send an email to this address when a SIS mirror fails. Comma separated list',
        label="SIS Mirror Notification Email(s)")

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='All Emails Enabled',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    parent_emails_header = FFields.ReadOnlyField(
        required=False,
        label=mark_safe('<h3 class="mt-4">Parent Notification(s)</h3>'),
        initial='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    parent_trigger = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        required=False,
        label='Parent/Counselor Status Trigger(s)',
        help_text='Status when notification is sent to parent and counselor',
        widget=forms.CheckboxSelectMultiple
    )

    parent_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Parent/Counselor Email Subject")

    parent_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Customize with {{student_first_name}}, {{student_email}}, {{course_name}}, {{campus}}, {{course_title}}, {{registration_status}}. <a href="#" class="float-right" onClick="do_bulk_action(\'registration_status_email\', \'parent_email\')" >See Preview</a>',
        label="Parent/Counselor Email")


    student_emails_header = FFields.ReadOnlyField(
        required=False,
        label=mark_safe('<h3 class="mt-4">Student Notification(s)</h3>'),
        initial='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )
    student_trigger = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        required=False,
        label='Student Email - Status Trigger(s)',
        help_text='Status when notification is sent to student',
        widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sis_mirror_terms'].choices = self._term_choices()
        self.fields['sis_mirror_stop_on_errors'].choices = self._known_error_choices()

        for k, v in StudentRegistration.STATUS_OPTIONS:
            self.fields[f"status_change_{k}_subject"] = forms.CharField(
                        widget=forms.TextInput,
                        help_text=f'{v} Subject',
                        required=False,
                        label=f'\'{v}\' Message Subject Line'
                    )
            
            self.fields[f"status_change_{k}_email"] = forms.CharField(
                        widget=forms.Textarea,
                        help_text='Message. Customize with {{student_first_name}}, {{student_last_name}}, {{student_email}}, {{course_name}}, {{status}}. <a href="#" class="float-right" onClick="do_bulk_action(\'registration_status_email\', \'' + f'status_change_{k}_email' + '\')" >See Preview</a>',
                        required=False,
                        label=f'\'{v}\' Message Email'
                    )

    @staticmethod
    def _term_choices():
        """(id, label) for the current campus's terms, newest first, each parent
        followed by its sub-terms (indented). Values are strings so the setting
        stays JSON."""
        from ..campus_context import scope_to_current_campus
        from ..services.term_hierarchy import term_tree_choices
        terms = scope_to_current_campus(
            Term.objects.select_related('academic_year'), 'academic_year__campus')
        return term_tree_choices(
            terms, label=lambda t: f"{t} ({t.code})", indent='— ')

    @classmethod
    def _known_error_choices(cls):
        """One checkbox per collected SIS error, newest first."""
        kinds = dict(SIS_ERROR_KINDS)
        known = (registration_status_email.from_db().get('sis_mirror_known_errors') or [])
        return [(e['key'], f"{kinds.get(e.get('kind'), e.get('kind'))}: {e.get('message', '')}"
                           f" (first seen {(e.get('first_seen') or '')[:10]})")
                for e in reversed(known) if isinstance(e, dict) and e.get('key')]

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        from ..models.crontab import CronTab
        cron, created = CronTab.objects.get_or_create(
            command='send_registrations_to_sis'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()
        
        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value
        
        return result

class registration_status_email(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_regis_status_email"
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

        email = email_settings.get(field_name)
        subject = email_settings.get(field_name)
        
        message = Template(email)
        context = Context({
            'student_first_name': "John",
            'student_last_name': "Smith",
            'student_email': "john@email.com",
            'course_name': "Course Name",
            'course_title': "Course Title",
            'campus': "Campus Name",
            'registration_status': 'Registration Status'
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
        defaults = {'is_active': 'Yes', 'parent_email': "<p style='font-size: 16px; line-height: 24px'>You are receiving this email on behalf of {{student_first_name}},</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>The course {{course_name}} at {{campus}} has changed to {{registration_status}}. Counselors can view the status change in ExplorEC. Parents please check with your student regarding this status change. </p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Thank you,</p>\r\n<p style='font-size: 16px; line-height: 24px'>&nbsp;</p>\r\n<p style='font-size: 16px; line-height: 24px'>Early College Administrators at {{campus}}</p>", 'parent_trigger': ['dropped', 'withdrawn'], 'section_drop_email': "<p style='font-size: 16px; line-height: 24px'>Dear {{student_first_name}},</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>The {{course_name}} that you were registered for at {{campus}} has been dropped. Please log into the ExplorEC portal to apply for a new course. </p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Thank you,</p>\r\n<p style='font-size: 16px; line-height: 24px'>&nbsp;</p>\r\n<p style='font-size: 16px; line-height: 24px'>Early College Administrators at {{campus}}</p>", 'section_full_email': "<p style='font-size: 16px; line-height: 24px'>Dear {{student_first_name}},</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>The {{course_name}} that you were registered for at {{campus}} has been cancelled. Please log into the portal to apply for a new course. </p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Thank you,</p>\r\n<p style='font-size: 16px; line-height: 24px'>&nbsp;</p>", 'parent_email_subject': 'Early College course status update', 'section_waitlist_email': "<p style='font-size: 16px; line-height: 24px'>Dear {{student_first_name}},</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>The {{course_name}} that you had applied for at {{campus}} has been waitlisted.</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Thank you,</p>\r\n<p style='font-size: 16px; line-height: 24px'>&nbsp;</p>\r\n<p style='font-size: 16px; line-height: 24px'>Early College Administrators at {{campus}}</p>", 'section_cancelled_email': "<h3>Hi {{student_first_name}},</h3>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Your application in the system has been processed, and you are now registered for the course {{course_name}} at {{campus}}. Please login if you need to make any changes to your account. </p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Sincerely,</p>\r\n<p style='font-size: 16px; line-height: 24px'>The Early College Team</p>", 'section_registered_email': "<h3>Hi {{student_first_name}},</h3>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Your application in ExplorEC has been processed, and you are now registered for the course {{course_name}} at {{campus}}. Please login to ExplorEC if you need to make any changes to your account. </p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Sincerely,</p>\r\n<p style='font-size: 16px; line-height: 24px'>The Early College Team</p>", 'section_drop_email_subject': 'Class Dropped', 'section_full_email_subject': 'Early College Class Application- Section is Full', 'section_waitlist_email_subject': 'Class Waitlisted', 'section_cancelled_email_subject': 'Early College Class registration confirmation', 'section_registered_email_subject': 'Early College Class registration confirmation'}

        Setting.install_defaults(self.key, defaults)

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def run_record(self):
        # Locked like record_sis_mirror_errors(), so an error the mirror adds
        # while the admin has the page open is kept, not overwritten.
        with transaction.atomic():
            setting = Setting.objects.select_for_update().filter(key=self.key).first()
            if setting is None:
                setting = Setting(key=self.key, value={})

            value = self._to_python()
            # non-dict entries are dropped on write
            known = [e for e in ((setting.value or {}).get('sis_mirror_known_errors') or [])
                     if isinstance(e, dict)]
            keys = {e.get('key') for e in known}
            value['sis_mirror_known_errors'] = known
            value['sis_mirror_stop_on_errors'] = [
                k for k in (value.get('sis_mirror_stop_on_errors') or []) if k in keys]
            setting.value = value
            setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
