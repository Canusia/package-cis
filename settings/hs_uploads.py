"""CE-configurable rules for files high schools upload (#56).

Stored in the Setting model under key ``cis.settings.hs_uploads`` as::

    {
      'allowed_extensions': 'pdf, xlsx, csv, jpg, png',
      'max_upload_mb': 100,
      'notify_emails': 'a@x.edu, b@x.edu',   # blank = no email
      'notify_subject': '...',               # Django template
      'notify_email': '...',                 # Django template
    }

Read through the classmethods, never the Setting row directly: an unset key
falls back to DEFAULTS, so a tenant that never saves this setting still gets
the shipped rules.
"""
from django import forms
from django.http import JsonResponse
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.settings import Setting


DEFAULTS = {
    'allowed_extensions': 'pdf, xlsx, csv, jpg, png',
    'max_upload_mb': 100,
    'notify_emails': '',
    'notify_subject': 'New file from {{highschool}}',
    'notify_email': (
        '{{uploaded_by}} uploaded {{file_name}} for {{highschool}} '
        '({{term}}).\n\n{{description}}\n\nReview it at {{link}}'
    ),
}


def _split(raw):
    return [part.strip() for part in (raw or '').split(',') if part.strip()]


class SettingForm(forms.Form):
    allowed_extensions = forms.CharField(
        label='Allowed File Types',
        help_text='Comma-separated file extensions, e.g. pdf, xlsx, csv, jpg, png.',
    )
    max_upload_mb = forms.IntegerField(
        min_value=1,
        label='Maximum File Size (MB)',
    )
    notify_emails = forms.CharField(
        required=False,
        label='Email These Addresses on Upload',
        help_text=('Comma-separated. Emailed whenever a high school administrator '
                   'uploads a file. Leave blank to send no email.'),
    )
    notify_subject = forms.CharField(
        required=False, max_length=200,
        label='Upload Email Subject',
    )
    notify_email = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 5}),
        label='Upload Email',
        help_text=('Placeholders: {{highschool}}, {{term}}, {{uploaded_by}}, '
                   '{{description}}, {{file_name}}, {{link}}.'),
    )

    def _to_python(self):
        return {
            'allowed_extensions': self.cleaned_data['allowed_extensions'],
            'max_upload_mb': self.cleaned_data['max_upload_mb'],
            'notify_emails': self.cleaned_data.get('notify_emails', ''),
            'notify_subject': self.cleaned_data.get('notify_subject', ''),
            'notify_email': self.cleaned_data.get('notify_email', ''),
        }


class hs_uploads(SettingForm):
    key = str(__name__)

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    @classmethod
    def get_config(cls):
        try:
            stored = Setting.objects.get(key=cls.key).value or {}
        except Setting.DoesNotExist:
            stored = {}
        return {**DEFAULTS, **stored}

    @classmethod
    def from_db(cls):
        return cls.get_config()

    @classmethod
    def allowed_extensions(cls):
        """Lower-case extensions without the dot, e.g. ['pdf', 'xlsx']."""
        return [ext.lower().lstrip('.')
                for ext in _split(cls.get_config().get('allowed_extensions'))]

    @classmethod
    def max_upload_bytes(cls):
        try:
            megabytes = int(cls.get_config().get('max_upload_mb'))
        except (TypeError, ValueError):
            megabytes = DEFAULTS['max_upload_mb']
        return megabytes * 1024 * 1024

    @classmethod
    def notify_recipients(cls):
        return _split(cls.get_config().get('notify_emails'))

    def install(self):
        Setting.install_defaults(self.key, dict(DEFAULTS))

    def run_record(self):
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting(key=self.key)
        setting.value = self._to_python()
        setting.save()
        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
