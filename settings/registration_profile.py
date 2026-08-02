"""Configurable detail layout for the StudentRegistration `asHTML` panel.

Stores a raw-JSON rows/columns layout under the `profile_display` key. When
unset/blank/invalid, StudentRegistration.asHTML falls back to
REGISTRATION_DEFAULT_DISPLAY (the historical hardcoded layout), so output is
unchanged until an admin configures it. Mirrors the minimal sis_settings
SettingForm pattern.
"""
import json

from django import forms
from django.http import JsonResponse
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.settings import Setting
from ..validators import validate_display_layout


# Verbatim active layout from StudentRegistration.asHTML (commented rows excluded).
REGISTRATION_DEFAULT_DISPLAY = [
    [
        {'label': 'SIS ID', 'field': 'sis_id'},
    ],
    [
        {'label': 'Student Signature', 'field': 'has_signed_student_agreement_pretty'},
    ],
    [
        {'label': 'Course', 'field': 'class_section.course'},
        {'label': 'Class #', 'field': 'class_section.class_number'},
    ],
    [
        {'label': 'Course Title', 'field': 'class_section.course.title'},
    ],
    [
        {'label': 'Course Schedule', 'field': 'class_section.schedule'},
        {'label': 'Term', 'field': 'class_section.term'},
    ],
    [
        {'field': 'class_section.teacher', 'label': 'Instructor'},
    ],
    [
        {'field': 'class_section.prereq', 'label': 'Pre-Req'},
    ],
    [
        'get_status',
        {'label': '', 'field': 'get_status_history'},
    ],
    [
        {'field': 'reviewer.user', 'label': 'Reviewer'},
    ],
]


class SettingForm(forms.Form):

    profile_display = forms.CharField(
        widget=forms.Textarea,
        required=False,
        validators=[validate_display_layout],
        label='Registration Detail Layout',
        help_text=(
            'Raw JSON layout for the staff Registration Details panel '
            '(StudentRegistration.asHTML). A list of rows; each row a list of '
            'columns; each column either "field_path" or {"field": "...", '
            '"label": "..."}. Leave blank to use the default layout.'
        ),
    )

    def _to_python(self):
        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value
        return result


class registration_profile(SettingForm):
    key = str(__name__)

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
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
        defaults = {'profile_display': json.dumps(REGISTRATION_DEFAULT_DISPLAY)}

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
