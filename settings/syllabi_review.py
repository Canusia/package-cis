import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy

from ..models.crontab import CronTab

from cis.models.term import AcademicYear, Term
from cis.services.term_hierarchy import apply_term_tree
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
    ending_date = forms.DateField(
        label="Email End Date (until)",
        help_text='Emails go out on the start and end dates too.'
    )

    cron = forms.CharField(
        max_length=20,
        # the site's own zone and check interval, not a fixed one (#117)
        help_text=(
            f'Min Hr Day Month WeekDay, in the site\'s time zone '
            f'({settings.TIME_ZONE}). Scheduled jobs are checked every few '
            'minutes, so a run goes out at the first check at or after the '
            'scheduled time.'
        ),
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
    
    portal_headers = FFields.ReadOnlyField(
        required=False,
        label=mark_safe(
            '<h2>Message displayed in instructor and faculty portal page(s)</h2>'
        ),
        initial='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    faculty_message = forms.CharField(
        max_length=None,
        required=False,
        widget=forms.Textarea,
        label="Needs Update Note Message",
        help_text='This is displayed in the page when faculty marks syllabi as needs update. <a href="#" class="float-right" onClick="do_bulk_action(\'syllabi_review\', \'faculty_message\')" >See Preview</a>'
    )

    instructor_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        label="Instructor Message",
        help_text='This is displayed to the instructors in their section details page under "Syllabi Tab". Customize with {{note}}. <a href="#" class="float-right" onClick="do_bulk_action(\'syllabi_review\', \'instructor_message\')" >See Preview</a>'
    )

    teacher_email_header = FFields.ReadOnlyField(
        required=False,
        label=mark_safe('<h2>Instructor Email Configuration - Sent to instructor after syllabus has been reviewed</h2>'
        ),
        initial='',
        widget=FFields.LongLabelWidget(
            attrs={
                'class':'border-0 bg-light h-100'
            }
        )
    )

    needs_update_email_subject = forms.CharField(
        max_length=500, label='Needs Review/Update - Subject')
    needs_update_email_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        label='Needs Review/Update - Message',
        validators=[validate_html_short_code],
        help_text='Email template sent to instructor when syllabi is marked as needs update, and as the needs update reminder (one email per instructor per term). Short codes supported {{instructor_first_name}}, {{instructor_last_name}}, {{term}}, {{course}}, {{course_name}}, {{note}}, {{section_list}} (reminder: each section with its note). <a href="#" class="float-right" onClick="do_bulk_action(\'syllabi_review\', \'email_message\')" >See Preview</a>'
    )

    reviewed_email_subject = forms.CharField(
        max_length=500, label='Approved/Reviewed - Subject')
    email_message_reviewed = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        label='Approved/Reviewed - Message',
        validators=[validate_html_short_code],
        help_text='Email template sent to instructor after syllabi is marked as reviewed. Short codes supported {{instructor_first_name}}, {{instructor_last_name}}, {{course}}, {{course_name}}, {{term}}. <a href="#" class="float-right" onClick="do_bulk_action(\'syllabi_review\', \'reviewed_message\')" >See Preview</a>'
    )

    # Shipped copy. A reader falls back to it whenever the saved setting has
    # no usable value, so an email never goes out as "None" (#110).
    DEFAULTS = {
        'missing_syllabus_email_subject': 'Class syllabus needed',
        'missing_syllabus_email_message': (
            'Hello {{instructor_first_name}},<br><br>'
            'Please upload the syllabus for the following class(es) in '
            '{{term}}:<br>{{section_list}}'),
        'needs_update_email_subject': 'Class syllabus needs update',
        'needs_update_email_message': (
            'Hello {{instructor_first_name}},<br><br>'
            'Your syllabus for {{course}} ({{term}}) has been marked as '
            'needs update.<br><br>{{note}}'),
        'reviewed_email_subject': 'Class syllabus reviewed',
        'email_message_reviewed': (
            'Hello {{instructor_first_name}},<br><br>'
            'Your syllabus for {{course_name}} ({{term}}) has been reviewed.'),
        'faculty_message': '',
        'instructor_message': '{{note}}',
    }

    # Email kind -> (subject key, body key) the form saves.
    EMAILS = {
        'missing_syllabus': (
            'missing_syllabus_email_subject', 'missing_syllabus_email_message'),
        'needs_update': (
            'needs_update_email_subject', 'needs_update_email_message'),
        'reviewed': ('reviewed_email_subject', 'email_message_reviewed'),
    }

    # Form key -> keys earlier versions read/stored the same copy under.
    # email_subject / email_message were the needs-update (and reviewed)
    # subject and body on the old pending_class_syllabi form.
    LEGACY_KEYS = {
        'needs_update_email_subject': ('email_subject',),
        'needs_update_email_message': ('email_message',),
        'reviewed_email_subject': ('email_subject',),
    }

    # What install() used to seed under the legacy keys: missing-syllabus
    # text, so it is not needs-update copy and must not be picked up.
    OLD_INSTALL_DEFAULTS = {
        'email_subject': 'Missing Syllabi',
        'email_message': '{{instructor_first_name}}, {{instructor_last_name}}, {{section_list}}, {{term}}',
    }

    @classmethod
    def resolve(cls, key, stored=None):
        """The value for a form key: the saved value, else a legacy key's,
        else the shipped default. Never None."""
        if stored is None:
            stored = cls.from_db()
        stored = stored if isinstance(stored, dict) else {}
        value = stored.get(key)
        if value:
            return value
        for legacy in cls.LEGACY_KEYS.get(key, ()):
            value = stored.get(legacy)
            if value and value != cls.OLD_INSTALL_DEFAULTS.get(legacy):
                return value
        return cls.DEFAULTS.get(key, '')

    @classmethod
    def email_template(cls, kind, stored=None):
        """(subject, body template source) for an email kind."""
        if stored is None:
            stored = cls.from_db()
        subject_key, body_key = cls.EMAILS[kind]
        return cls.resolve(subject_key, stored), cls.resolve(body_key, stored)

    def clean_term(self):
        data = self.cleaned_data.get('term')
        return [str(d.id) for d in data]

    def clean(self):
        cleaned = super().clean()
        starting_date = cleaned.get('starting_date')
        ending_date = cleaned.get('ending_date')
        # Compare the parsed dates: re-parsing the raw input with one format
        # broke on ISO dates and an empty start date (#128).
        if starting_date and ending_date and starting_date > ending_date:
            self.add_error('ending_date', 'End Date has to be after start date.')
        # Stored as m/d/Y, which notify_missing_syllabi parses.
        for key in ('starting_date', 'ending_date'):
            if isinstance(self.cleaned_data.get(key), datetime.date):
                self.cleaned_data[key] = self.cleaned_data[key].strftime('%m/%d/%Y')
        return self.cleaned_data

    # See Preview link field -> (email kind, or None, body key for a page message)
    PREVIEWS = {
        'email': ('missing_syllabus', None),
        'email_message': ('needs_update', None),
        'reviewed_message': ('reviewed', None),
        'faculty_message': (None, 'faculty_message'),
        'instructor_message': (None, 'instructor_message'),
    }

    def preview(self, request, field_name):
        from django.http import HttpResponse
        from django.shortcuts import render
        from django.template import Context, Template
        from django.utils.html import format_html

        if field_name not in self.PREVIEWS:
            return JsonResponse({'message': 'Unknown preview'}, status=400)

        kind, body_key = self.PREVIEWS[field_name]
        stored = self.from_db()
        if kind:
            subject, source = self.email_template(kind, stored)
        else:
            subject, source = None, self.resolve(body_key, stored)

        # sample values for every short code documented on this page
        context = Context({
            'instructor_first_name': 'Dale',
            'instructor_last_name': 'Smith',
            'section_list': mark_safe('<br>'.join(
                ['ACC 101/12345/001', 'ACC 102/12346/001'])),
            'term': 'Fall 2026',
            'course': 'ACC 101',
            'course_name': 'ACC 101',
            'note': 'Add a grading scale.',
        })
        body = Template(source).render(context)

        if not kind:
            return HttpResponse(format_html('<div class="p-3">{}</div>', mark_safe(body)))

        message = format_html(
            '<p><strong>Subject:</strong> {}</p><hr>{}', subject, mark_safe(body))
        return render(request, 'cis/email.html', {'message': message})

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

        apply_term_tree(self.fields['term'], Term.objects.all().order_by('-code'))

        # A field the saved setting has no value for shows the copy readers
        # would actually send (legacy key, else default), so saving the form
        # keeps it rather than dropping it (#110). Copied first: callers pass
        # the stored Setting.value itself as initial.
        stored = self.initial
        self.initial = dict(stored)
        for key in self.DEFAULTS:
            if key in self.fields and not self.initial.get(key):
                self.initial[key] = self.resolve(key, stored)

    def install(self):
        defaults = {"mode": "test", "testers": "kadaji@gmail.com", **self.DEFAULTS}

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