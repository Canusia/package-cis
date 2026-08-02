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

class ParentConsentForm(forms.Form):

    request_consent_intro = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Displayed before consent request form. <a href="#" class="float-right" onClick="do_bulk_action(\'parentconsent\', \'request_consent_intro\')" >See Preview</a>',
        label="Intro.")

    consent_terms = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='<a href="#" class="float-right" onClick="do_bulk_action(\'parentconsent\', \'consent_terms\')" >See Preview</a>',
        label="Parent Consent Term(s)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'request_consent_intro': self.cleaned_data['request_consent_intro'],
            'consent_terms': self.cleaned_data['consent_terms']
        }


class parentconsent(ParentConsentForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_parent_consent"
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

        from cis.models.student import Student, ParentConsent
        from cis.settings.student_portal import student_portal as portal_lang
        from cis.forms.student import StudentForm, ParentConsentForm, ParentConsentRequestForm

        form = ParentConsentForm(initial={
            'student': '-1',
            'consent_terms': ParentConsent.get_form_message('consent_terms'),
            'term': '-1'
        })

        consent_req_form = ParentConsentRequestForm(initial={
            'student': -1,
            'term': -2,
            'parent_name': "Parent Name",
            'parent_email': "Parent Email"
        })

        return render(
            request,
            'student/parent_consent.html', {
                'form': form,
                'student': None,
                'consent_req_form': consent_req_form,
                'has_parent_consent': False,
                'message': {
                    'request_consent': ParentConsent.get_form_message(),
                    'consent_terms': ParentConsent.get_form_message('consent_terms')
                },
                'intro': portal_lang(request).from_db().get('parent_consent_blurb', 'Change me'),
                'menu': '-1'
            })

    def install(self):
        defaults = {
            'request_consent_intro': 'Change Me',
            'consent_terms': 'Change Me'
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
