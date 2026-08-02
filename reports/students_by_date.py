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
from cis.models.student import Student
from cis.models.term import Term
from cis.models.section import StudentRegistration
from cis.models.course import Campus
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus


class students_by_date(forms.Form):
    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    applied_on = forms.DateField(
        required=True,
        label='Created Account On and After',
        widget=forms.DateInput(attrs={'class': 'col-md-6 col-sm-12'})
    )

    applied_until = forms.DateField(
        required=True,
        label='Created Account Until',
        widget=forms.DateInput(attrs={'class': 'col-md-6 col-sm-12'})
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
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        self.fields['term'].queryset = Term.objects.all().order_by('-code')

        # Populate the campus selector with only the campuses the requesting
        # user may process (superusers see all prefixed campuses).
        if self.request:
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    def get_result(self, data, user=None):
        records = Student.objects.select_related(
            'user',
            'highschool'
        ).filter(
            user__created_at__gte=datetime.datetime.strptime(data.get('applied_on')[0], '%m/%d/%Y'),
            user__created_at__lt=datetime.datetime.strptime(data.get('applied_until')[0], '%m/%d/%Y'),
        )

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        records = scope_report_by_campus(
            records, user, data.get('campus'),
            campus_path='studentregistration__class_section__course__campus',
            distinct=True)

        return records

    def run(self, task, data):
        # `task` is the ReportScheduler; task.created_by is the requesting user
        # (there is no request in the background task, so gate by the scheduler).
        records = self.get_result(data, user=getattr(task, 'created_by', None))

        # Get student IDs who have registrations in the selected term
        student_ids = set(
            str(sid) for sid in StudentRegistration.objects.filter(
                class_section__registration_term__id__in=data.get('term')
            ).values_list('student_id', flat=True).distinct()
        )

        file_name = "student-export.csv"
        fields = {
            'id': 'Canusia Id',
            'user.psid': 'User ID',
            'user.first_name': 'First Name',
            'user.last_name': 'Last Name',
            'user.middle_name': 'Middle Name',
            'user.suffix': 'Suffix',
            'preferred_name': 'Preferred Name',
            'user.email': 'Email',
            'highschool': 'High School',
            'highschool.code': 'High School CEEB',
            'highschool.sau': 'High School BLDG Code',
            'cte': 'CTE',
            'graduation_year': 'Graduation Year',
            'qualify_tuition_assistance': 'Qualify for Tuition Assistance',
            'user.date_of_birth': 'Date of Birth',
            'us_citizen': 'US Citizen',
            'user.ssn': 'SSN',
            'gender': 'Gender',
            'user.primary_phone': 'Cell Phone',
            'can_receive_sms': 'Can Receive SMS',
            'secondary_phone': 'Home Phone',
            'user.address1': 'Mailing Address',
            'user.city': 'City',
            'user.state': 'State',
            'user.postal_code': 'Zip Code',
            'hispanic': 'Hispanic',
            'ethnicity': 'Race',
            'parent_name': 'Parent 1 Name',
            'parent_email': 'Parent 1 Email',
            'parent_phone': 'Parent 1 Phone',
            'parent2_name': 'Parent 2 Name',
            'parent2_email': 'Parent 2 Email',
            'parent2_phone': 'Parent 2 Phone',
            '_parent1_education_level': 'Parent 1 Education Level',
            '_parent2_education_level': 'Parent 2 Education Level',
            'parent1_interest_pretty': 'Parent 1 Interest',
            'parent2_interest_pretty': 'Parent 2 Interest',
            'start_term': 'Start Term',
        }

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        writer.writerow(list(fields.values()) + ['Applied For Class'])
        for record in records.iterator():
            row = []
            for key in fields.keys():
                row.append(
                    force_str(get_field(record, key))
                )

            row.append('Yes' if str(record.id) in student_ids else 'No')
            writer.writerow(row)

        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path

    def run_report(self):
        ...
