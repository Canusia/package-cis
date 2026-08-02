import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError
from django.shortcuts import (
    render, get_object_or_404,
    redirect
)

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.settings import Setting

class SettingForm(forms.Form):

    intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed in top of "Apply for Classes" page. <a href="#" class="float-right" onClick="do_bulk_action(\'class_search\', \'intro\')" >See Preview</a>',
        label="Intro.")

    tab_search_for_classes = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed in \'Search for Class(es)\' Tab.  <a href="#" class="float-right" onClick="do_bulk_action(\'class_search\', \'tab_search_for_classes\')" >See Preview</a>',
        label="Tab # Search for Class(es)")

    tab_ec_classes = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed in \'EC Class(es)\' Tab.  <a href="#" class="float-right" onClick="do_bulk_action(\'class_search\', \'tab_ec_classes\')" >See Preview</a>',
        label="Tab # EC Classes")

    tab_my_classes = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed in \'My Class Application(s)\' Tab.  <a href="#" class="float-right" onClick="do_bulk_action(\'class_search\', \'tab_my_classes\')" >See Preview</a>',
        label="Tab # My Class Application(s)")

    ftr_tab_my_classes = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed at bottom of My Class Tab.  <a href="#" class="float-right" onClick="do_bulk_action(\'class_search\', \'ftr_tab_my_classes\')" >See Preview</a>',
        label="Footer # My Class")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'intro': self.cleaned_data['intro'],
            'tab_search_for_classes': self.cleaned_data['tab_search_for_classes'],
            'tab_ec_classes': self.cleaned_data['tab_ec_classes'],
            'tab_my_classes': self.cleaned_data['tab_my_classes'],
            'ftr_tab_my_classes': self.cleaned_data['ftr_tab_my_classes']
        }

class class_search(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_apply_classes"
    
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
        from cis.models.section import StudentRegistration

        template = 'student/classes.html'
        return render(
            request,
            template,
            {
                'has_signed_agreement': True,
                'message': {
                    'intro': StudentRegistration.get_form_message('intro'),
                    'tab_apply': StudentRegistration.get_form_message('tab_search_for_classes'),
                    'tab_ec_classes': StudentRegistration.get_form_message('tab_ec_classes'),
                    'tab_my_classes': StudentRegistration.get_form_message('tab_my_classes'),
                    'tab_ftr_my_classes': StudentRegistration.get_form_message('ftr_tab_my_classes')
                }
            },
        )

    def install(self):
        defaults = {
            'intro': "Change this in Settings -> Students -> Class Search",
            'tab_search_for_classes': "Change this in Settings -> Students -> Class Search",
            'tab_ec_classes': "Change this in Settings -> Students -> Class Search",
            'tab_my_classes': "Change this in Settings -> Students -> Class Search",
            'ftr_tab_my_classes': "Change this in Settings -> Students -> Class Search",
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
