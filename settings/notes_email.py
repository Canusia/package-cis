import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.settings import Setting
from cis.validators import validate_html_short_code

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

    teacherapplication_note_to_instructor_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Teacher SI Application Note - Email Subject")

    teacherapplication_note_to_instructor_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent to applicant after a \'to_instructor\' note is added. Customize with {{note}}, {{instructor_first_name}}, {{instructor_last_name}}, {{reply_url}}',
        label="Teacher SI Application Note - Email"
    )

    class_section_note_to_instructor_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Class Section Note to Instructor - Email Subject")

    class_section_note_to_instructor_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent to instructor after a \'to_instructor\' note is added. Customize with {{note}}, {{instructor_first_name}}, {{instructor_last_name}}',
        label="Class Section Note to Instructor - Email"
    )


    note_to_instructor_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Note to Instructor - Email Subject")

    note_to_instructor_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent to instructor after a \'to_instructor\' note is added. Customize with {{note}}, {{instructor_first_name}}, {{instructor_last_name}}',
        label="Note to Instructor - Email"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value

class notes_email(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_notes_email"
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
            'is_active': "Debug",
            'class_section_note_to_instructor_subject': "Change this in Settings -> Misc -> Subject",
            'class_section_note_to_instructor_email': "Change this in Settings -> Misc -> Email",
            'note_to_instructor_subject': "Change this in Settings -> Misc -> Subject",
            'note_to_instructor_email': "Change this in Settings -> Misc -> Email",
            'teacherapplication_note_to_instructor_subject': "Change this in Settings -> Misc -> Subject",
            'teacherapplication_note_to_instructor_email': "Change this in Settings -> Misc -> Email",
        }

        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

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
