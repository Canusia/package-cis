import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError
from django_ckeditor_5.widgets import CKEditor5Widget as CKEditorWidget

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.term import Term, AcademicYear
from ..models.settings import Setting

class SettingForm(forms.Form):

    ferpa_intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed before FERPA form. <a href="#" class="float-right" onClick="do_bulk_action(\'ferpa\', \'ferpa_intro\')" >See Preview</a>',
        label="Intro.")


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'ferpa_intro': self.cleaned_data['ferpa_intro']
        }


class ferpa(SettingForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_ferpa"
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
        
        from cis.models.student import StudentFerpa
        from cis.settings.student_portal import student_portal as portal_lang
        from cis.services.tenant_services import get_tenant_service

        service = get_tenant_service('ferpa_form')
        # `student` is a required positional (used to look up an existing
        # record); there is no student behind a setting preview.
        form = service.StudentFerpaForm(None, initial={
            'student': '-1'
        })
        return render(
            request,
            service.form_template(), {
                'form': form,
                'student': None,
                'ferpa': None,
                'message': {
                    'intro': StudentFerpa.get_form_message()
                },
                'menu': None,
                'intro': portal_lang(request).from_db().get('ferpa_blurb', 'Change me'),
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
            'ferpa_intro': "Change this in Settings -> Students -> FERPA",
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
