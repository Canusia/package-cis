from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..validators import validate_cron, numeric, validate_html_short_code
from ..models.crontab import CronTab
from ..models.settings import Setting


class SettingForm(forms.Form):
    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No'),
        ('Debug', 'Debug'),
    ]

    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Enabled',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    window_days = forms.CharField(
        max_length=3,
        help_text='Send reminders when a credential is due within this many days.',
        label='Look-ahead Window (days)',
        validators=[numeric])

    frequency = forms.CharField(
        max_length=2,
        help_text='Re-send the reminder every N days while still due.',
        label='Frequency (days)',
        validators=[numeric])

    cron = forms.CharField(
        max_length=20,
        help_text='Min Hr Day Month WeekDay',
        label='Cron Expression',
        validators=[validate_cron])

    email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label='Email Subject')

    email_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Supports HTML. Shortcodes: {{teacher_first_name}}, {{teacher_last_name}}, {{course_name}}, {{highschool_name}}, {{renewal_due_date}}, {{expires_on}}. <a href="#" class="float-right" onClick="do_bulk_action(\'teacher_certificate_renewal\', \'email_message\')" >See Preview</a>',
        label='Email')

    def _to_python(self):
        cron, created = CronTab.objects.get_or_create(
            command='notify_certificate_renewal'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        return {
            'is_active': self.cleaned_data['is_active'],
            'cron': self.cleaned_data['cron'],
            'window_days': self.cleaned_data['window_days'],
            'frequency': self.cleaned_data['frequency'],
            'email_subject': self.cleaned_data['email_subject'],
            'email_message': self.cleaned_data['email_message'],
        }


class teacher_certificate_renewal(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX') + "_teacher_certificate_renewal"

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'
        if request is not None:
            self.helper.form_action = reverse_lazy(
                'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    def preview(self, request, field_name):
        from django.template import Context, Template
        from django.shortcuts import render

        email_settings = self.from_db()
        email = email_settings.get('email_message', '')

        email_template = Template(email)
        context = Context({
            'teacher_first_name': request.user.first_name,
            'teacher_last_name': request.user.last_name,
            'course_name': 'ENGL& 101',
            'highschool_name': 'Sample High School',
            'renewal_due_date': '06/30/2026',
            'expires_on': '06/30/2026',
        })
        text_body = email_template.render(context)
        return render(request, 'cis/email.html', {'message': text_body})

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        defaults = {'is_active': 'Debug'}
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
