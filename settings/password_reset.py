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

    allowed_roles = forms.MultipleChoiceField(
        choices=[],
        label='Who can reset their password?',
        widget=forms.CheckboxSelectMultiple
    )

    # password_reset_subject = forms.CharField(
    #     max_length=None,
    #     help_text='Password Reset Email Subject',
    #     label="Password Reset Email Subject")

    # password_reset_email = forms.CharField(
    #     max_length=None,
    #     widget=forms.Textarea,
    #     # validators=[validate_html_short_code],
    #     label="Password Reset Confirmation Email")
    
    post_password_reset_subject = forms.CharField(
        max_length=None,
        help_text='Email Subject sent after password has been reset',
        label="Password Reset Confirmation Email Subject")

    post_password_reset_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Customize with {{first_name}}, {{last_name}}. <a href="#" class="float-right" onClick="do_bulk_action(\'password_reset\', \'email\')" >See Preview</a>',
        label="Password Reset Confirmation Email")
    
    bulk_password_reset_subject = forms.CharField(
        max_length=None,
        help_text='',
        label="Bulk Password Reset Confirmation Email Subject")

    bulk_password_reset_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        validators=[validate_html_short_code],
        help_text='Simple Text ONLY. Customize with {{first_name}}, {{last_name}}, {{new_password}}. <a href="#" class="float-right" onClick="do_bulk_action(\'password_reset\', \'bulk_password_reset_email\')" >See Preview</a>',
        label="Bulk Password Reset Confirmation Email (Text Only)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        roles = getattr(settings, 'MY_CE').get('roles', [])
        role_choices = []
        for role_id, role in roles.items():
            role_choices.append(
                (role_id, role.get('nice_name'))
            )

        self.fields['allowed_roles'].choices = role_choices

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'allowed_roles': self.cleaned_data['allowed_roles'],
            
            'post_password_reset_subject': self.cleaned_data['post_password_reset_subject'],
            'post_password_reset_email': self.cleaned_data['post_password_reset_email'],

            # 'password_reset_subject': self.cleaned_data['password_reset_subject'],
            # 'password_reset_email': self.cleaned_data['password_reset_email'],
            
            'bulk_password_reset_subject': self.cleaned_data['bulk_password_reset_subject'],
            'bulk_password_reset_email': self.cleaned_data['bulk_password_reset_email']
        }


class password_reset(SettingForm):
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

    def preview(self, request, field_name):

        from django.template.loader import get_template, render_to_string
        from django.template import Context, Template
        from django.shortcuts import render, get_object_or_404

        email_settings = self.from_db()

        if field_name == 'email':
            email = email_settings.get('password_reset_email')
            subject = email_settings.get('password_reset_subject')
        if field_name == 'bulk_password_reset_email':
            email = email_settings.get('bulk_password_reset_email')
            subject = email_settings.get('bulk_password_reset_subject')

        email_template = Template(email)
        context = Context({
            'first_name': request.user.first_name,
            'last_name': request.user.last_name,
            # 'report_download_url': "https://report-download-url",
            # 'report_title': 'Report Title',
            'new_password': 'NEW PASSWORD'
        })

        text_body = email_template.render(context)
        
        return render(
            request,
            'cis/email.html',
            {
                'message': text_body
            }
        )

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        defaults = {
            'password_reset_subject': 'Change me in Settings -> Misc',
            'password_reset_email': "Change me in Settings -> Misc"
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
