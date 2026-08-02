import io
import csv

from django import forms
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.student import ParentConsent, StudentAgreement
from cis.models.term import Term
from cis.models.course import Campus
from cis.models.section import StudentRegistration
from cis.models.highschool import HighSchool
from cis.utils import get_field
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus
from cis.reports.datasource_mixin import ReportDataSourceMixin

class class_roster(ReportDataSourceMixin, forms.Form):

    # Usable as a bulk-mailer datasource (announcement): every field below is a
    # {{shortcode}} embeddable in the bulk message.
    datasource_descriptor = 'Students on the class roster, by term, high school, and registration status.'
    email_column = 'email'
    name_columns = ['FirstName', 'LastName']
    datasource_fields = {
        'FirstName': 'student.user.first_name',
        'LastName': 'student.user.last_name',
        'email': 'student.user.email',
        'StudentID': 'student.user.psid',
        'CRN': 'class_section.class_number',
        'Course': 'class_section.course.name',
        'TermCode': 'class_section.term.code',
        'Term': 'class_section.term.label',
        'HighSchool': 'class_section.highschool.name',
        'SchoolType': 'class_section.highschool.hs_type_display',
        'Grade': 'grade',
        'Status': 'get_status',
        'StudentBalance': 'student.current_student_balance',
        'SchoolBalance': 'student.current_school_balance',
    }

    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    term = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Term(s)'
    )

    highschool = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Student High School(s)'
    )

    registration_status = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        required=False,
        label='Registration Status'
    )

    roles = []
    request = None
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        self.fields['term'].queryset = Term.objects.all()

        if request:
            self.roles = request.user.get_roles()
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')])

            if 'ce' in self.roles:
                # if request.user has ce role
                self.fields['highschool'].queryset = HighSchool.objects.all()

            elif 'highschool_admin' in self.roles:
                highschool_ids = self.request.user.get_highschools_for_admin()
                self.fields['highschool'].queryset = HighSchool.objects.filter(
                    id__in=highschool_ids
                )

    def get_result(self, data, user=None):
        term_id = data.get('term')

        records = StudentRegistration.objects.select_related(
            'class_section__course',
            'class_section__term',
            'class_section__highschool',
            'student__user'
        ).only(
            'id', 'status', 'grade', 'student_id',
            'class_section_id',
            'class_section__class_number',
            'class_section__term_id',
            'class_section__term__code',
            'class_section__term__label',
            'class_section__course__name',
            'class_section__highschool__name',
            'student__current_student_balance',
            'student__current_school_balance',
            'student__user__first_name',
            'student__user__last_name',
            'student__user__psid'
        ).filter(
            class_section__term__id__in=term_id,
            student__highschool__id__in=data.get('highschool')
        )

        statuses = data.get('registration_status')
        if statuses:
            records = records.filter(status__in=statuses)

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        records = scope_report_by_campus(
            records, user, data.get('campus'),
            campus_path='class_section__course__campus')

        return records


    def recipient_queryset(self, data):
        """Datasource recipients: StudentRegistration rows for the selected
        terms / high schools / registration statuses (with relations for the
        shortcode fields)."""
        records = StudentRegistration.objects.select_related(
            'student__user',
            'class_section__course',
            'class_section__term',
            'class_section__highschool',
        )
        terms = data.get('term')
        highschools = data.get('highschool')
        statuses = data.get('registration_status')
        if terms:
            records = records.filter(class_section__term__id__in=terms)
        if highschools:
            records = records.filter(student__highschool__id__in=highschools)
        if statuses:
            records = records.filter(status__in=statuses)

        # Campus gate: scope to the requesting user (available via self.request
        # when this datasource is used interactively from the bulk mailer UI).
        records = scope_report_by_campus(
            records, getattr(self, 'request', None) and self.request.user,
            data.get('campus'),
            campus_path='class_section__course__campus')

        return records

    def run(self, task, data):
        records = self.get_result(data, user=getattr(task, 'created_by', None))
        term_ids = data.get('term')

        # Prefetch consent and agreement data to avoid N+1 queries
        student_ids = list(records.values_list('student_id', flat=True))

        consent_set = set(
            ParentConsent.objects.filter(
                student_id__in=student_ids,
                term_id__in=term_ids
            ).values_list('student_id', 'term_id')
        )

        agreement_set = set(
            StudentAgreement.objects.filter(
                student_id__in=student_ids,
                term_id__in=term_ids
            ).values_list('student_id', 'term_id')
        )

        file_name = "roster-export.csv"
        fields = {
            'class_section.class_number': 'CRN',
            'class_section.course.name': 'Course',
            'class_section.term.code': 'Term Code',
            'class_section.term.label': 'Term',
            'class_section.highschool.name': 'Class Section High School',
            'class_section.highschool.hs_type_display': 'School Type',
            'student.user.first_name': 'Student First Name',
            'student.user.last_name': 'Student Last Name',
            'student.user.psid': 'Student ID',
            'grade': 'Grade',
            'student.current_student_balance': 'Current Student Balance',
            'student.current_school_balance': 'Current School Balance',
        }

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        header = list(fields.values()) + ['Status', 'Parent Consent', 'Student Agreement']
        writer.writerow(header)

        for record in records.iterator():
            row = []
            for key in fields.keys():
                row.append(
                    force_str(get_field(record, key))
                )

            # Call get_status() method for human-readable status
            row.append(record.get_status)

            # Use prefetched sets for consent/agreement lookups (O(1) instead of DB query)
            consent_key = (record.student_id, record.class_section.term_id)
            row.append('Received' if consent_key in consent_set else 'Pending')
            row.append('Received' if consent_key in agreement_set else 'Pending')

            writer.writerow(row)
        
        path = "reports/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path
    
    def run_report(self):
        ...