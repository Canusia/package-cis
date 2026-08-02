import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.validators import validate_html_short_code
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

    student_note_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Student Email Subject")

    student_note_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent with note added. Must contain {{note}}. Customize with {{student_first_name}}, {{student_last_name}}, {{created_by_first_name}}, {{created_by_last_name}}, {{created_by_email}}.',
        label="Student Email")

    student_note_parent_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Student Parent Email Subject")

    student_note_parent_message = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Email template sent with note added. Must contain {{note}}. Customize with {{parent_first_name}}, {{parent_last_name}} {{student_first_name}}, {{student_last_name}}, {{created_by_first_name}}, {{created_by_last_name}}, {{created_by_email}}.',
        label="Student Parent Email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'is_active': self.cleaned_data['is_active'],
            'student_note_subject': self.cleaned_data['student_note_subject'],
            'student_note_message': self.cleaned_data['student_note_message'],

            'student_note_parent_subject': self.cleaned_data['student_note_parent_subject'],
            'student_note_parent_message': self.cleaned_data['student_note_parent_message'],
            
            # 'student_note_counselor_subject': self.cleaned_data['student_note_counselor_subject'],
            # 'student_note_counselor_message': self.cleaned_data['student_note_counselor_message'],
        }


class student_notes_email(SettingForm):
    key = str(__name__)

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
        defaults = {'is_active': 'Yes', 'student_note_message': "<p style='font-size: 16px; line-height: 24px'>Dear {{student_first_name}},</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>The following note has been added to your account by {{created_by_first_name}} {{created_by_last_name}}. You can contact them at {{created_by_email}}</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>{{note}}</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Thank you,</p>\r\n<p style='font-size: 16px; line-height: 24px'>&nbsp;</p>", 'student_note_subject': 'Note added to your account', 'student_note_parent_message': "<p style='font-size: 16px; line-height: 24px'>Dear {{parent_first_name}},</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>The following note has been added to your student's account by {{created_by_first_name}} {{created_by_last_name}}. You can contact them at {{created_by_email}}</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>{{note}}</p>\r\n\r\n<p style='font-size: 16px; line-height: 24px'>Thank you,</p>\r\n<p style='font-size: 16px; line-height: 24px'>&nbsp;</p>", 'student_note_parent_subject': "Note added to your student's account"}

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
