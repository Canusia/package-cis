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

from ..validators import numeric

from cis.utils import sanitize_plain_text

class SettingForm(forms.Form):

    mode = forms.ChoiceField(
        choices=(('test', 'Testing'), ('active', 'Active')),
        required=True
    )

    email_subject = forms.CharField(
        label='Email Subject'
    )

    email_message = forms.CharField(
        widget=forms.Textarea,
        help_text='Simple text email. Customize with {{first_name}}, {{last_name}}, {{verification_code}}',
        label="Email Message")
    
    text_message = forms.CharField(
        widget=forms.Textarea,
        help_text='Customize with {{first_name}}, {{last_name}}, {{verification_code}}',
        label="Text Message")

    verification_page_header = forms.CharField(
        widget=forms.Textarea,
        help_text='Customize with {{phone_last4}}, {{email_address}}',
        label="Verification Page Header")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST.

        PT-16: ``verification_page_header`` is rendered on the public
        two-step verification page, so strip all HTML markup before
        persisting it. The legitimate ``{{phone_last4}}`` /
        ``{{email_address}}`` placeholders contain no angle brackets and
        survive ``sanitize_plain_text`` unchanged.
        """
        return {
            'mode': self.cleaned_data['mode'],
            'email_subject': self.cleaned_data['email_subject'],
            'email_message': self.cleaned_data['email_message'],
            'text_message': self.cleaned_data['text_message'],
            'verification_page_header': sanitize_plain_text(
                self.cleaned_data['verification_page_header']
            ),
        }


class two_step(SettingForm):
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

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        defaults = {
            'is_active': 'No',
            'footer': 'Change me in Settings -> Misc -> SMS',
            'from_phone': '19282186718'
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
