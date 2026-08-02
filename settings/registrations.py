import json, datetime
from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.highschool import HighSchool
from ..models.term import Term, AcademicYear
from ..models.settings import Setting

class RegistrationForm(forms.Form):
    academic_year = forms.ChoiceField(
        choices=[],
        label='Active Academic Year',
    )

    homeschool = forms.ChoiceField(
        choices=[],
        required=False,
        label='Home School',
        help_text='Select the home school from the list'
    )

    active_term = forms.ChoiceField(
        choices=[],
        # help_text='Registrations from the above term(s) will be cleared upon next import',
        label="Active Term")

    signature_term = forms.ChoiceField(
        choices=[],
        widget=forms.HiddenInput,
        required=False,
        help_text='Term for which student and parent signature will be collected',
        label="Signature/Recommendation for Term")

    registration_terms = forms.MultipleChoiceField(
        choices=[],
        help_text='Term(s) for which students can register',
        label="Registration Term(s)")
    
    # college_start_terms = forms.MultipleChoiceField(
    #     choices=[],
    #     help_text='College Start Term(s) that students can choose',
    #     label="College Start Term(s)")

    tuition_assistance_ending_date = forms.DateField(label="Scholarship App Open Until")
    tuition_pay_end_date = forms.DateField(label="Tuition Pay Open Until")

    window_close_notice = forms.CharField(
        max_length=None,
        widget=forms.Textarea,
        help_text='<a href="#" class="float-right" onClick="do_bulk_action(\'registrations\', \'window_close_notice\')" >See Preview</a>',
        label="Message when Registration is Closed")

    starting_date = forms.DateField(label="Opens On")
    ending_date = forms.DateField(label="Open Until")
    
    # instructor_review_ending_date = forms.DateField(
    #     label="Instructor Review Open Until"
    # )

    starting_birth_date = forms.DateField(
        label="Starting Birth Date"
    )
    ending_birth_date = forms.DateField(
        label="Ending Birth Date"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        term_choices = []
        for term in Term.objects.all():
            term_choices.append((str(term.id), term))

        self.fields['academic_year'].choices = [
            (str(acad_year.id), acad_year) for acad_year in AcademicYear.objects.all()
        ]

        self.fields['homeschool'].choices = [('','Select')] + [
            (str(school.id), school.name) for school in HighSchool.objects.all().order_by('name')
        ]

        # self.fields['signature_term'].choices = term_choices
        self.fields['active_term'].choices = term_choices
        self.fields['registration_terms'].choices = term_choices
        # self.fields['college_start_terms'].choices = term_choices

    def _to_python(self):
        """
        Return dict of form elements from $_POST
        """
        return {
            'academic_year': self.cleaned_data['academic_year'],
            'homeschool': self.cleaned_data.get('homeschool'),
            'active_term': self.cleaned_data['active_term'],
            'registration_terms': self.cleaned_data['registration_terms'],
            # 'college_start_terms': self.cleaned_data['college_start_terms'],
            'signature_term': self.cleaned_data.get('signature_term'),
            'window_close_notice': self.cleaned_data['window_close_notice'],
            'starting_date': self.cleaned_data['starting_date'],
            'tuition_assistance_ending_date': self.cleaned_data['tuition_assistance_ending_date'],
            'tuition_pay_end_date': self.cleaned_data['tuition_pay_end_date'],
            'ending_date': self.cleaned_data['ending_date'],
            # 'instructor_review_ending_date': self.cleaned_data['instructor_review_ending_date'],
            'starting_birth_date': self.cleaned_data['starting_birth_date'],
            'ending_birth_date': self.cleaned_data['ending_birth_date'],
        }

    def clean_tuition_assistance_ending_date(self):
        data = self.cleaned_data['tuition_assistance_ending_date']
        return data.strftime('%m/%d/%Y')
    
    def clean_tuition_pay_end_date(self):
        data = self.cleaned_data['tuition_pay_end_date']
        return data.strftime('%m/%d/%Y')
    
    def clean_starting_date(self):
        data = self.cleaned_data['starting_date']
        return data.strftime('%m/%d/%Y')
    
    def clean_instructor_review_ending_date(self):
        data = self.cleaned_data['instructor_review_ending_date']
        return data.strftime('%m/%d/%Y')

    def clean_ending_date(self):
        starting_date = datetime.datetime.strptime(
            self.data.get('starting_date'), '%m/%d/%Y'
        )

        ending_date = datetime.datetime.strptime(
            self.data.get('ending_date'), '%m/%d/%Y'
        )

        if starting_date > ending_date:
            raise ValidationError(
                _(f'Open Until date has to be after Opens On date.')
            )

        data = self.cleaned_data['ending_date']
        return data.strftime('%m/%d/%Y')

    def clean_starting_birth_date(self):
        data = self.cleaned_data['starting_birth_date']
        return data.strftime('%m/%d/%Y')

    def clean_ending_birth_date(self):
        starting_birth_date = datetime.datetime.strptime(
            self.data.get('starting_birth_date'), '%m/%d/%Y'
        )

        ending_birth_date = datetime.datetime.strptime(
            self.data.get('ending_birth_date'), '%m/%d/%Y'
        )

        if starting_birth_date > ending_birth_date:
            raise ValidationError(
                _(f'Ending birth date has to be after starting date.')
            )

        data = self.cleaned_data['ending_birth_date']
        return data.strftime('%m/%d/%Y')

class registrations(RegistrationForm):
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
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

        from cis.models.student import Student
        from cis.forms.student import StudentForm
        from cis.forms.customuser import DemoRequestForm, MyCELoginForm

        form = MyCELoginForm(request)

        key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
        if field_name in ['window_close_notice']:

            window_close_notice = Setting.get_value(key, "window_close_notice")
            return render(
                request,
                'cis/index/student.html',
                {
                    'registration_terms': None,
                    'registration_is_open': False,
                    'window_close_notice': window_close_notice,
                    'form': form
                })
        

    @classmethod
    def asHTML(cls):
        try:
            setting = cls.from_db()

            result = '<div class="details">'
            result += "<div class='row p-2'>"
            result += f"<div class='col-md-12 mt-2'>"

            result += "<div class='detail_label'>Term(s)</div>"
            result += "<div class=''>"
            terms = Term.objects.filter(
                pk__in=setting.get('registration_terms', [])
            )
            term_labels = []
            for term in terms:
                term_labels.append(str(term))

            result += ', '.join(term_labels)
            result += "</div>"
            result += "<div class='clearfix'>&nbsp;</div>"

            result += "<div class='detail_label'>Registration Period</div>"
            result += "<div class=''>"
            result += setting.get('starting_date', '') + ' - ' + setting.get('ending_date', '')
            result += "</div>"
            result += "<div class='clearfix'>&nbsp;</div>"

            result += "<div class='detail_label'>Allowed Birth Dates</div>"
            result += "<div class=''>"
            result += setting.get('starting_birth_date', '') + ' - ' + setting.get('ending_birth_date', '')
            result += "</div>"
            result += "<div class='clearfix'>&nbsp;</div>"
            
            result += "<div class='detail_label'>Active Year & Term</div>"
            result += "<div class=''>"
            
            try:
                active_year = AcademicYear.objects.filter(
                    pk=setting.get('academic_year', [])
                )
                active_term = Term.objects.filter(
                    pk=setting.get('active_term', [])
                )

                result += str(active_year[0]) + '&nbsp;/&nbsp;' + str(active_term[0])
            except Exception as e:
                print(e)
                pass
            result += "</div>"
            result += "</div></div></div>"

            return result
        except Exception as e:
            return ''

    @classmethod
    def from_db(cls):
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        defaults = {
            'academic_year': '',
            'homeschool': '',
            'active_term': '',
            'registration_terms': '',
            'signature_term': '',
            'window_close_notice': '',
            'starting_date': '',
            'ending_date': '',
            'starting_birth_date': '',
            'ending_birth_date': '',
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

            