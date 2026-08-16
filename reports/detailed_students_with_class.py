import io
import csv

from django import forms
from django.db.models import Count
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import get_field, registration_terms
from cis.models.term import Term
from cis.models.course import Campus
from cis.models.section import StudentRegistration
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus

class detailed_students_with_class(forms.Form):
    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    term = forms.ModelMultipleChoiceField(
        queryset=None
    )

    status = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        label='Registration Status'
    )

    roles = []
    request = None
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        # self.helper.attrs = {'target':'_blank'}
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
        term_id = data.get('term')
        status = data.get('status')

        records = StudentRegistration.objects.select_related(
            'student__user',
            'student__highschool__district',
            'class_section__term__academic_year',
            'class_section__course',
            # Instructor columns below read class_section.teacher.user; without
            # this the export issues two extra queries per row.
            'class_section__teacher__user',
        ).filter(
            class_section__term__id__in=term_id,
            status__in=status
        )

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        records = scope_report_by_campus(
            records, user, data.get('campus'),
            campus_path='class_section__course__campus')

        return records

    def run(self, task, data):
        # `task` is the ReportScheduler; task.created_by is the requesting user
        # (there is no request in the background task, so gate by the scheduler).
        records = self.get_result(data, user=getattr(task, 'created_by', None))

        # Prefetch total_approved_sections counts to avoid N+1 queries
        student_ids = list(records.values_list('student_id', flat=True).distinct())
        reg_terms = registration_terms()
        approved_statuses = ['approved_by_instructor', 'registered', 'approved']

        approved_counts = dict(
            StudentRegistration.objects.filter(
                student_id__in=student_ids,
                class_section__term__in=reg_terms,
                status__in=approved_statuses
            ).values('student_id').annotate(
                count=Count('id')
            ).values_list('student_id', 'count')
        )

        file_name = "student-class-export.csv"
        fields = {
            'student.id': 'Canusia ID',
            'student.user.first_name': 'First Name',
            'student.user.last_name': 'Last Name',
            'student.user.middle_name': 'Middle Name',
            'student._gender': 'Gender',
            'student.user.date_of_birth': 'DoB',
            'student.user.address1': 'Address',
            'student.user.city': 'City',
            'student.user.state': 'State',
            'student.user.postal_code': 'Zip',
            'student.highschool.district': 'School District',
            'student.highschool': 'High School',
            'student.user.email': 'Email',
            'student.user.primary_phone': 'Cell Phone',
            'student.can_receive_sms': 'Cell Phone Opt-in',
            'student.user.created_at': 'AccountCreatedOn',
            'student.graduation_year': 'Graduation Year',

            'student.parent_name': 'Parent Name',
            'student.parent_email': 'Parent Email',
            'student.parent_phone': 'Parent Phone',

            'student.parent2_name': 'Parent 2 Name',
            'student.parent2_email': 'Parent 2 Email',
            'student.parent2_phone': 'Parent 2 Phone',

            'student.user.psid': 'Student ID',
            'student.current_student_balance': 'Current Student Balance',
            'student.current_school_balance': 'Current School Balance',

            'class_section.term.academic_year': 'Academic Year',
            'class_section.term': 'Term',
            'class_section.course': 'Course',
            'class_section.course.title': 'Title',
            'class_section.class_number': 'Class No.',
            'class_section.section_number': 'Section No.',
            'class_section.course.credit_hours': 'Credits',
            'class_section.teacher.user.first_name': 'Instructor First Name',
            'class_section.teacher.user.last_name': 'Instructor Last Name',
            'class_section.grade_status': 'Class Grade Status',

            'note': 'note',
            'sexy_status': 'Status',
            'grade': 'Grade',
        }

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        header = list(fields.values()) + ['Total Approved Sections']
        writer.writerow(header)

        for record in records.iterator():
            row = []
            for key in fields.keys():
                row.append(
                    force_str(get_field(record, key))
                )

            # Use prefetched count instead of N+1 property call
            row.append(approved_counts.get(record.student_id, 0))

            writer.writerow(row)
        
        path = "reports/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path

    def run_report(self):
        ...
