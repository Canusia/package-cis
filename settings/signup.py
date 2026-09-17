import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from django.utils.html import format_html, format_html_join

from cis.validators import validate_html_short_code, validate_json
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.settings import Setting

#: Every key the signup flow looks up in the `error_messages` JSON, in the
#: order they appear to a student. The value is free-form JSON, so this
#: catalogue is the only place an admin can learn what is settable -- it drives
#: the field's help text, and cis.tests.test_signup_error_messages_help pins it
#: against the readers (student/views/onboarding.py and each tenant's
#: verify_email_form). Add the key here in the same change that reads it.
SIGNUP_ERROR_MESSAGE_KEYS = {
    'start_app': [
        ('success', 'Application started; check your email to verify.'),
        ('error', 'The application could not be created.'),
        ('form_validation_fail', 'The form has errors to correct.'),
        ('dup_email.account_unverified',
         'Email already on file, not yet verified (a new link is sent).'),
        ('dup_email.incomplete_application',
         'Email already on file and verified, but no password was ever set.'),
        ('dup_email.being_processed',
         'Email already on file, application in progress.'),
        ('dup_email.pending_ernie_login',
         'Email already on file; the student should sign in with campus credentials.'),
        ('dup_email.non_student_account_exists',
         'Email already on file on a non-student account.'),
    ],
    'verify_email': [
        ('invalid_token', 'The verification link does not match the student.'),
        ('account_already_verified', 'The email was verified previously.'),
        ('success', 'The email was verified just now.'),
    ],
    'complete_signup': [
        ('awaiting_processing_error', 'The application is still being processed.'),
        ('error', 'The application could not be completed.'),
        ('success', 'The application was received.'),
        ('form_validation_fail', 'The form has errors to correct.'),
    ],
}


def _error_messages_help_text():
    """Help text listing every supported key, grouped by section.

    Any key left unset falls back to wording in the code, so an admin only
    needs to add the ones they want to reword -- notably the four
    start_app.dup_email keys, which are the only way to word what a student
    sees when their email is already on file.
    """
    sections = format_html_join(
        '', '<li><code>{}</code><ul>{}</ul></li>',
        (
            (section, format_html_join(
                '', '<li><code>{}</code> &mdash; {}</li>',
                ((key, description) for key, description in keys)))
            for section, keys in SIGNUP_ERROR_MESSAGE_KEYS.items()
        ))
    return format_html(
        'Valid JSON. Supported keys (all optional &mdash; anything omitted '
        'falls back to the built-in wording):<ul>{}</ul>', sections)


# --- Signup message catalog --------------------------------------------------
# Every user-facing string in the student self-signup flow lives here and is
# overridable per tenant through the `error_messages` JSON on this setting.
#
# Two rules, both learned the hard way:
#
#   1. install() seeds from this dict, so the seeded key name can never drift
#      from the key the readers use. It did drift ('error_message' vs
#      'error_messages'), which left the whole catalog unreachable and made
#      ValidationError(None) render to the student as the literal text "None".
#   2. Readers must go through message() below, never a bare .get() chain. A
#      tenant whose JSON predates a new key still gets real text instead of
#      None or a blank alert box.
DEFAULT_MESSAGES = {
    'start_app': {
        'success': 'Please check your email for further instructions',
        'error': 'Unable to create application. The administrator has been '
                 'notified.',
        'form_validation_fail': 'Unable to complete request. Please correct the '
                                'error(s) and try again',
        'dup_email': {
            'non_student_account_exists':
                'An account with this email already exists. Unable to create a '
                'student account. Please contact our office for further '
                'assistance',
            'account_unverified':
                'An account with this email already exists. A verification link '
                'has been emailed to this address. Please see that email for '
                'further instructions',
            # Verified, but the application was never finished: no password was
            # ever set, so the account cannot be logged into and cannot be
            # re-created. Forgot Password re-issues a verification link for
            # exactly this state -- see cis/views/password_management.py.
            'incomplete_application':
                'An account with this email already exists, but the application '
                'was never finished. Go to the login page and choose "Forgot '
                'Password" to have a new link emailed to you, then pick up where '
                'you left off.',
            # The application is finished and this student has a password --
            # nothing is blocking them and there is nothing for them to do
            # here. Say only that the account exists; the old copy promised
            # someone would contact them, which read as "you are stuck waiting"
            # when in fact they can simply log in.
            'being_processed':
                'An account with this email already exists. Please log in.',
            'pending_ernie_login':
                'An account with this email already exists. Please login with '
                'your college credentials',
        },
    },
    'verify_email': {
        'invalid_token':
            'This verification link has already been used or is no longer '
            'valid. If you did not finish setting your password, go to the '
            'login page and choose "Forgot Password" to have a new link emailed '
            'to you.',
        'account_already_verified':
            'Your email has already been verified. Please log in. If you never '
            'set a password, choose "Forgot Password" on the login page to have '
            'a new link emailed to you.',
        'success': 'Your email has been successfully verified. Please continue',
    },
    'complete_signup': {
        'awaiting_processing_error': 'Your application is currently being '
                                     'processed. Please contact our office for '
                                     'further assistance',
        'error': 'Unable to create application. The administrator has been '
                 'notified.',
        'success': 'We have received your application. You will receive an '
                   'email once you are ready to register for classes.',
        'form_validation_fail': 'Unable to complete request. Please correct the '
                                'error(s) and try again',
    },
}


def message(section, key, subsection=None):
    """Resolve one signup message, falling back to DEFAULT_MESSAGES.

    ``section`` is a top-level key ('start_app', 'verify_email',
    'complete_signup'); ``subsection`` an optional nested group ('dup_email').
    Never returns None for a key that exists in DEFAULT_MESSAGES, however
    malformed, stale or absent the tenant's JSON is.
    """
    try:
        configured = json.loads(signup.from_db().get('error_messages') or '{}')
    except (json.JSONDecodeError, TypeError, AttributeError):
        configured = {}

    def _pick(source):
        # error_messages is free-text JSON a tenant edits by hand in Settings,
        # so every level has to be checked, not just the parse. Valid JSON of
        # the wrong shape -- a top-level list, or "dup_email": "some text"
        # where an object belongs -- otherwise raises AttributeError out of a
        # .get(), 500s the signup page, and takes the fallback down with it.
        branch = source
        for step in (section, subsection):
            if step is None:
                continue
            if not isinstance(branch, dict):
                return None
            branch = branch.get(step)
        if not isinstance(branch, dict):
            return None
        value = branch.get(key)
        # A nested object here would reach the page as "{'a': 'b'}".
        return value if isinstance(value, str) else None

    return _pick(configured) or _pick(DEFAULT_MESSAGES)


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
        help_text=_error_messages_help_text(),
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
        # 'error_messages' (plural) is the key every reader looks up. Seeding it
        # from DEFAULT_MESSAGES keeps the two in step; a hand-written JSON string
        # here is what drifted to 'error_message' and broke the whole flow.
        defaults = {
            'email_verify_intro': 'Change Me',
            'awaiting_verify_intro': '',
            'confirm_verify_intro': '',
            'intro': '<section class="jumbotron text-center bg-transparent">\r\n <div class="container">\r\n <div class="trans-bg rounded p-2">\r\n <h1 class="jumbotron-heading">Welcome to MyCE Demo Portal</h1>\r\n <h3>Your portal to concurrent enrollment</h3>\r\n<p class="alert alert-info">Please complete the form to start your application</p>\r\n </div>\r\n </div>\r\n </section>',
            'verify_form_field_messages': '{}',
            'signup_terms': 'Change this in Settings -> Students -> Signup Page',
            'student_terms': 'Change this in Settings -> Students -> Signup Page',
            'error_messages': json.dumps(DEFAULT_MESSAGES),
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        # Fill in what is missing; never overwrite what is already stored.
        # register_settings only reaches install() when the SettingRecord is
        # absent, so this fires on an existing Setting row only where the two
        # have drifted apart -- but when it does, an unconditional assignment
        # wipes both a tenant's edited wording and the repair
        # myce_tenant_configs.0001_ewu_signup_message_catalog performs, and the
        # whole message catalog now lives under this key.
        # `field not in value`, not `not value.get(field)`: signup_terms is
        # required=False, so a tenant can deliberately save it empty and must
        # not have the placeholder text put back.
        value = setting.value if isinstance(setting.value, dict) else {}
        for field, default in defaults.items():
            if field not in value:
                value[field] = default

        setting.value = value
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
