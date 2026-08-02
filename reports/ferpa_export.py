import io
import csv
import datetime

from django import forms
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import get_field
from cis.models.student import StudentFerpa
from cis.models.term import Term
from cis.models.course import Campus
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus
from cis.services.tenant_services import get_tenant_service


class ferpa_export(forms.Form):
    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    applied_on = forms.DateField(
        required=True,
        label='Created Account On and After',
        widget=forms.DateInput(attrs={'class':'col-md-6 col-sm-12'})
    )
    
    applied_until = forms.DateField(
        required=True,
        label='Created Account Until',
        widget=forms.DateInput(attrs={'class':'col-md-6 col-sm-12'})
    )

    term = forms.ModelChoiceField(
        queryset=None,
        label='Registration Term',
        help_text='Term(s) for which the student has applied for at least one class'
    )

    roles = []
    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'

        # for cis users only show their campus
        if self.request:
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

        self.fields['term'].queryset = Term.objects.all().order_by('-code')

        self.helper.add_input(Submit('submit', 'Generate Export'))


    def get_result(self, data, user=None):
        records = StudentFerpa.objects.select_related(
            'student__user',
            'student__highschool'
        ).filter(
            student__user__created_at__gte=datetime.datetime.strptime(data.get('applied_on')[0], '%m/%d/%Y'),
            student__user__created_at__lt=datetime.datetime.strptime(data.get('applied_until')[0], '%m/%d/%Y'),
        )

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        records = scope_report_by_campus(
            records, user, data.get('campus'),
            campus_path='student__studentregistration__class_section__course__campus',
            distinct=True)

        return records

    def run(self, task, data):
        # `task` is the ReportScheduler; task.created_by is the requesting user
        # (there is no request in the background task, so gate by the scheduler).
        records = self.get_result(data, user=getattr(task, 'created_by', None))

        file_name = "student-ferpa-export.csv"
        fields = {
            'student.id': 'Canusia ID Number',
            'student.user.first_name': 'Student Legal First Name',
            'student.user.last_name': 'Student Legal Last Name',
            'student.user.middle_name': 'Middle Name or Initial',
            'student.user.psid': 'Student ID',
            'student.preferred_name': 'Chosen First Name',
            'student.highschool.code': 'High School',
            'student.highschool_graduation_month': 'High School Graduation Month',
            'student.highschool_graduation_year': 'High School Graduation Year',
            'student.user.email': 'Student Personal Email',
            'student.user.country_of_birth': 'Country of Birth',
            'student.user.date_of_birth': 'Date of Birth',
            'student.user.primary_phone': 'Cell Phone Number'
        }

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        # Header: base fields + the tenant's FERPA columns (release info and
        # however many contacts that tenant's form collects).
        service = get_tenant_service('ferpa_form')
        header = list(fields.values()) + service.export_headers()
        writer.writerow(header)

        for record in records.iterator():
            row = []
            for key in fields.keys():
                row.append(
                    force_str(get_field(record, key))
                )

            row.extend(service.export_row(record))

            writer.writerow(row)
        
        path = "reports/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path
    
    def run_report(self):
        ...