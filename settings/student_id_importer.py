import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import FILE_DELIMITER
from ..models.crontab import CronTab
from ..models.term import Term, AcademicYear
from ..models.settings import Setting

from ..validators import validate_cron

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
    
    path_to_results_file = forms.CharField(
        max_length=200,
        help_text='{{hh}}, {{mm}}, {{dd}}, {{yyyy}}',
        label="Relative Path to import results file")

    notification_list = forms.CharField(
        max_length=200,
        help_text='Comma separated notifier email list',
        label="Notification List")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        cron, created = CronTab.objects.get_or_create(
            command='import_student_id_from_ethos'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        return {
            'is_active': self.cleaned_data['is_active'],
            'cron': self.cleaned_data['cron'],
            'notification_list': self.cleaned_data['notification_list'],
            'path_to_results_file': self.cleaned_data['path_to_results_file'],
        }


class student_id_importer(SettingForm):
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
