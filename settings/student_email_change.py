"""CE setting "Student Portal - Change Email" (#79, ported from nnu#15 / ewu#80).

Registered through CisConfig.CONFIGURATORS; key cis.settings.student_email_change.
"""
from django import forms
from django.http import JsonResponse
from django.shortcuts import render
from django.template import Context, Template
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.validators import validate_html_short_code
from ..models.settings import Setting

DEFAULTS = {
    'verification_subject': 'Verify your new email address',
    'verification_message': (
        '<p>Hi {{first_name}},</p>'
        '<p>We received a request to change your account email to {{new_email}}. '
        'Enter this code to confirm:</p>'
        '<p style="font-size:24px;font-weight:bold;letter-spacing:4px">{{code}}</p>'
        '<p>The code expires in {{expires_minutes}} minutes. '
        'If you did not request this, you can ignore this email.</p>'
    ),
    'confirmation_subject': 'Your account email was changed',
    'confirmation_message': (
        '<p>Hi {{first_name}},</p>'
        '<p>The email on your account was changed from {{old_email}} to {{new_email}} on {{changed_on}}.</p>'
        '<p>If you did not make this change, contact our office immediately.</p>'
    ),
    'code_ttl_minutes': 15,
    'max_attempts': 5,
    'resend_cooldown_seconds': 60,
    'max_requests_per_day': 5,
}

LIMIT_KEYS = ('code_ttl_minutes', 'max_attempts', 'resend_cooldown_seconds', 'max_requests_per_day')


def get_config():
    """Setting value merged over DEFAULTS, with limits coerced to int."""
    conf = {**DEFAULTS, **student_email_change.from_db()}
    for k in LIMIT_KEYS:
        try:
            conf[k] = int(conf[k])
        except (TypeError, ValueError):
            conf[k] = DEFAULTS[k]
    return conf


class SettingForm(forms.Form):
    verification_subject = forms.CharField(
        max_length=200,
        label='Verification Code Email Subject')

    verification_message = forms.CharField(
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Sent to the NEW address. Must contain {{code}}. Customize with {{first_name}}, {{last_name}}, {{new_email}}, {{expires_minutes}}. <a href="#" class="float-right" onClick="do_bulk_action(\'student_email_change\', \'verification_message\')">See Preview</a>',
        label='Verification Code Email')

    confirmation_subject = forms.CharField(
        max_length=200,
        label='Email Changed Confirmation Subject')

    confirmation_message = forms.CharField(
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Sent to BOTH the old and new address after the change. Customize with {{first_name}}, {{last_name}}, {{old_email}}, {{new_email}}, {{changed_on}}. <a href="#" class="float-right" onClick="do_bulk_action(\'student_email_change\', \'confirmation_message\')">See Preview</a>',
        label='Email Changed Confirmation Email')

    code_ttl_minutes = forms.IntegerField(
        min_value=1, max_value=1440,
        label='Code Expires After (minutes)')

    max_attempts = forms.IntegerField(
        min_value=1, max_value=20,
        label='Max Incorrect Code Attempts',
        help_text='After this many wrong codes the student must request a new code.')

    resend_cooldown_seconds = forms.IntegerField(
        min_value=0, max_value=3600,
        label='Wait Before Resending Code (seconds)')

    max_requests_per_day = forms.IntegerField(
        min_value=1, max_value=100,
        label='Max Email Change Requests per Student (rolling 24 hours)')

    def clean_verification_message(self):
        data = self.cleaned_data['verification_message']
        if '{{code}}' not in data.replace(' ', ''):
            raise ValidationError('The verification email must contain {{code}}.')
        return data

    def _to_python(self):
        return {k: self.cleaned_data[k] for k in DEFAULTS}


class student_email_change(SettingForm):
    key = str(__name__)

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'
        # Only set form_action if report_id is present, following payment_routing.py pattern
        if request is not None and getattr(request, 'GET', None):
            report_id = request.GET.get('report_id')
            if report_id:
                self.helper.form_action = reverse_lazy(
                    'setting:run_record', args=[report_id])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def preview(self, request, field_name):
        conf = get_config()
        context = Context({
            'first_name': request.user.first_name,
            'last_name': request.user.last_name,
            'new_email': 'new.address@example.com',
            'old_email': 'old.address@example.com',
            'code': '123456',
            'expires_minutes': conf['code_ttl_minutes'],
            'changed_on': 'January 1, 2026 9:00 AM',
        })
        text_body = Template(conf.get(field_name, '')).render(context)
        return render(request, 'cis/email.html', {'message': text_body})

    @classmethod
    def from_db(cls):
        try:
            return Setting.objects.get(key=cls.key).value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        # Seeds missing keys only; never overwrites CE edits (package-cis #19).
        Setting.install_defaults(self.key, dict(DEFAULTS))

    def run_record(self):
        setting, _ = Setting.objects.get_or_create(key=self.key, defaults={'value': {}})
        setting.value = self._to_python()
        setting.save()
        return JsonResponse({'message': 'Successfully saved settings', 'status': 'success'})
