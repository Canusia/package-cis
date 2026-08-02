import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.template import Context, Template
from django.urls import reverse_lazy
from django.utils import timezone
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.validators import validate_html_short_code
from cis.utils import sftp_check_read_write
from ..models.crontab import CronTab
from ..models.term import Term, AcademicYear
from ..models.settings import Setting

from ..validators import (
    validate_cron,
    validate_filename_hhmmddyyyy,
    validate_relative_path
)

SECRET_FIELDS = ('password', 'private_key')


class SettingForm(forms.Form):
    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No')
    ]

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Enabled',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay',
        label="Cron Expression",
        validators=[validate_cron]
    )

    host_name = forms.CharField(
        max_length=200,
        help_text='',
        label="Host Name"
    )

    port = forms.IntegerField(
        min_value=1,
        max_value=65535,
        initial=22,
        help_text='',
        label="Port"
    )

    username = forms.CharField(
        max_length=100,
        help_text='',
        label="Username"
    )

    password = forms.CharField(
        max_length=100,
        required=False,
        help_text='Leave blank to keep the existing password.',
        widget=forms.PasswordInput(render_value=False),
        label="Password"
    )

    private_key = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 6, 'autocomplete': 'off'}),
        label="Private Key (PEM)",
        help_text='Optional. Used instead of password if provided. Leave blank to keep existing key.'
    )

    path_to_file = forms.CharField(
        max_length=200,
        help_text='{{min}}, {{hh}}, {{mm}}, {{dd}}, {{yyyy}}',
        label="Path to export file",
        validators=[validate_filename_hhmmddyyyy, validate_html_short_code]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements, preserving stored secrets if blanks were submitted.
        """
        cron, created = CronTab.objects.get_or_create(
            command='export_student_data'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        existing = student_exporter.from_db() or {}
        new_password = self.cleaned_data.get('password') or existing.get('password', '')
        new_private_key = self.cleaned_data.get('private_key') or existing.get('private_key', '')

        return {
            'is_active': self.cleaned_data['is_active'],
            'cron': self.cleaned_data['cron'],
            'path_to_file': self.cleaned_data['path_to_file'],
            'host_name': self.cleaned_data['host_name'],
            'port': self.cleaned_data['port'],
            'username': self.cleaned_data['username'],
            'password': new_password,
            'private_key': new_private_key,
        }


def _render_remote_path(template_str):
    now = timezone.localtime(timezone.now())
    return Template(template_str or '').render(Context({
        'min': now.strftime("%M"),
        'hh': now.strftime("%H"),
        'mm': now.strftime("%m"),
        'dd': now.strftime("%d"),
        'yyyy': now.strftime("%Y"),
    }))


class student_exporter(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX') + str(__name__)

    def __init__(self, request, *args, **kwargs):
        # Seed initial values from saved settings (excluding secret fields)
        # only when the form is being rendered (no POST data).
        if not args and 'data' not in kwargs:
            existing = student_exporter.from_db() or {}
            initial = kwargs.get('initial', {}) or {}
            for k, v in existing.items():
                if k in SECRET_FIELDS:
                    continue
                initial.setdefault(k, v)
            kwargs['initial'] = initial

        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned

        existing = student_exporter.from_db() or {}
        effective_password = cleaned.get('password') or existing.get('password', '')
        effective_pkey = cleaned.get('private_key') or existing.get('private_key', '')

        if not effective_password and not effective_pkey:
            raise ValidationError("Provide either a password or a private key.")

        # Skip the live SFTP probe if the integration is disabled.
        if cleaned.get('is_active') != 'Yes':
            return cleaned

        try:
            sftp_check_read_write(
                host=cleaned.get('host_name'),
                port=cleaned.get('port') or 22,
                username=cleaned.get('username'),
                password=effective_password or None,
                private_key=effective_pkey or None,
                remote_path=_render_remote_path(cleaned.get('path_to_file')),
            )
        except Exception as exc:
            raise ValidationError(f"SFTP credentials failed read/write check: {exc}")

        return cleaned

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    @classmethod
    def from_db_safe(cls):
        """Same as from_db() but with secrets stripped, for view/template use."""
        value = cls.from_db() or {}
        return {k: v for k, v in value.items() if k not in SECRET_FIELDS}

    def install(self):
        defaults = {
            'is_active': "No",
        }

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
