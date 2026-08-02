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

class SettingForm(forms.Form):
    
    non_logged = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed in non-logged pages. <a href="#" class="float-right" onClick="do_bulk_action(\'footer\', \'non_logged\')" >See Preview</a>',
        label="Non-Logged Page(s) Footer")

    logged_staff = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed in CEP staff pages. <a href="#" class="float-right" onClick="do_bulk_action(\'footer\', \'logged_staff\')" >See Preview</a>',
        label="Logged Staff Page(s) Footer")

    logged_student = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed in Student pages. <a href="#" class="float-right" onClick="do_bulk_action(\'footer\', \'logged_student\')" >See Preview</a>',
        label="Logged Student Page(s) Footer")

    logged_hsadmin = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed in School Admin pages. <a href="#" class="float-right" onClick="do_bulk_action(\'footer\', \'logged_hsadmin\')" >See Preview</a>',
        label="Logged School Admin. Page(s) Footer")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'non_logged': self.cleaned_data['non_logged'],
            'logged_staff': self.cleaned_data['logged_staff'],
            'logged_student': self.cleaned_data['logged_student'],
            'logged_hsadmin': self.cleaned_data['logged_hsadmin'],
        }


class footer(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_footer"
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
        from django.conf import settings

        from cis.models.student import Student
        from cis.models.term import AcademicYear
        from cis.models.course import Cohort, Course
        from cis.forms.student import StudentForm
        from cis.settings.faculty_portal import faculty_portal as portal_lang

        
        if field_name in ['non_logged']:
            template = 'cis/base.html'
            return render(
                request,
                template,
                {
                    'page_title': 'Class Sections',
                    'urls': {},
                    'menu': None,
                    'intro': portal_lang(request).from_db().get('classes_blurb', 'Change me'),
                    'class_sections_api': '/ce/api/class_section?format=datatables',
                    'academic_years': AcademicYear.objects.all().order_by('-name'),
                    'active_academic_year': None,
                }
            )
        else:
            template = 'cis/logged-base.html'
            return render(
                request,
                template,
                {
                    'page_title': 'Class Sections',
                    'urls': {},
                    'menu': None,
                    'intro': portal_lang(request).from_db().get('classes_blurb', 'Change me'),
                    'class_sections_api': '/ce/api/class_section?format=datatables',
                    'academic_years': AcademicYear.objects.all().order_by('-name'),
                    'active_academic_year': None,
                })

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        defaults = {
            'non_logged': 'Change me in Settings -> Misc',
            'logged_staff': "Change me in Settings -> Misc",
            'logged_student': "Change me in Settings -> Misc",
            'logged_hsadmin': "Change me in Settings -> Misc",
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
