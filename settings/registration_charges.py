import json
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.validators import validate_html_short_code, validate_email_list, validate_cron
from ..models.crontab import CronTab
from ..models.term import Term, AcademicYear
from ..models.section import StudentRegistration
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
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'})
    )

    hs_pay_type = forms.ChoiceField(
        choices=[
            ('class_highschool', 'Class High School'),
            ('student_highschool', 'Student High School')
        ],
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'})
    )
    
    charge_trigger = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        label='Registration Charge Addition Trigger(s)',
        help_text='Status when charge is added'
    )

    charge_remove_trigger = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        label='Registration Charge Removal Trigger(s)',
        help_text='Status when charge is removed'
    )

    ta_status_updated_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="TA Request Updated Subject")

    ta_status_updated_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Email template sent when TA has been updated. Customize with {{student_first_name}}, {{student_last_name}}, {{student_balance}}, {{ta_term}}, {{public_note}}, {{status}}',
        label="TA Request Updated Email")
    

    STATUS_OPTIONS = [
        ('', 'Select'),
        ('active', 'Active'),
        ('debug', 'Debug')
    ]

    mode = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Mode',
        help_text='',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}))

    cron = forms.CharField(
        max_length=50,
        help_text='Min Hr Day Month WeekDay',
        label="Cron Expression for Sending Missing Payment Reminder",
        validators=[validate_cron]
    )

    parent_bill_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        label="Bill Pay Subject")

    parent_bill_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='Email template sent when bill is due. Customize with {{student_first_name}}, {{student_last_name}}, {{payment_url}}, {{active_term}}, {{bill_due_date}}',
        label="Bill Pay Email")

    payment_received_email_subject = forms.CharField(
        max_length=200,
        help_text='',
        required=False,
        label="Payment Received Subject")

    payment_received_email = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        required=False,
        help_text='Email template sent to student and parent when payment is received. Customize with {{student_first_name}}, {{student_last_name}}, {{payment_amount}}, {{payment_date}}',
        label="Payment Received Email")

    # parent_bill_pay_intro = forms.CharField(
    #     max_length=None,
    #     widget=forms.Textarea,
    #     help_text='',
    #     label="Bill Pay Page Intro")
    
    invoice_template_header = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='',
        label="Invoice Template Header")
    
    invoice_template_footer = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='',
        label="Invoice Template Footer")
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        
        cron, created = CronTab.objects.get_or_create(
            command='send_missing_payment_reminder'
        )
        cron.cron = self.cleaned_data.get('cron')
        cron.save()

        return {
            'is_active': self.cleaned_data['is_active'],
            'charge_trigger': self.cleaned_data['charge_trigger'],
            'charge_remove_trigger': self.cleaned_data['charge_remove_trigger'],
            'ta_status_updated_email_subject': self.cleaned_data['ta_status_updated_email_subject'],
            'ta_status_updated_email': self.cleaned_data['ta_status_updated_email'],
            'invoice_template_header': self.cleaned_data['invoice_template_header'],
            'invoice_template_footer': self.cleaned_data['invoice_template_footer'],
            'parent_bill_email_subject': self.cleaned_data['parent_bill_email_subject'],
            'parent_bill_email': self.cleaned_data['parent_bill_email'],
            'payment_received_email_subject': self.cleaned_data['payment_received_email_subject'],
            'payment_received_email': self.cleaned_data['payment_received_email'],
            # 'parent_bill_pay_intro': self.cleaned_data['parent_bill_pay_intro'],
            'cron': self.cleaned_data['cron'],
            'mode': self.cleaned_data['mode'],
        }


class registration_charges(SettingForm):
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
            'charge_trigger': ['registered'],
            'charge_remove_trigger': ['dropped']
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
