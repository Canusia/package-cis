import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..validators import (
    validate_cron, validate_email_list, validate_filename_hhmmddyyyy,
    validate_relative_path, validate_html_short_code
)

from ..models.crontab import CronTab
from ..models.term import Term, AcademicYear
from ..models.settings import Setting

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

    terms = forms.MultipleChoiceField(
        label='Terms',
        help_text='Sections will be pulled from SIS for each selected term on every cron run.',
        widget=forms.SelectMultiple(attrs={'class': 'col-md-8 col-sm-12', 'size': 10}),
    )

    path_to_results_file = forms.CharField(
        max_length=200,
        validators=[validate_filename_hhmmddyyyy, validate_relative_path, validate_html_short_code],
        help_text='{{hh}}, {{mm}}, {{dd}}, {{yyyy}}',
        label="Relative Path to results file (CSV)")

    notification_list = forms.CharField(
        max_length=200,
        help_text='Comma separated notifier email list',
        validators=[validate_email_list],
        label="Notification List")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['terms'].choices = [
            (str(term.id), f"{term.label} ({term.code})")
            for term in Term.objects.select_related('academic_year').all()
        ]

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        cron, created = CronTab.objects.get_or_create(
            command='import_class_sections'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        return {
            'is_active': self.cleaned_data['is_active'],
            'cron': self.cleaned_data['cron'],
            'terms': self.cleaned_data['terms'],
            'path_to_results_file': self.cleaned_data['path_to_results_file'],
            'notification_list': self.cleaned_data['notification_list'],
        }


class class_section_importer(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX') + str(__name__)

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

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
