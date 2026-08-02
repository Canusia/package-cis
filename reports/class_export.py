import io, csv, datetime

from django import forms
from django.db.models import Q, Count
from django.urls import reverse_lazy
from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.encoding import force_str
from django.core.files.base import ContentFile, File

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import (
    export_to_excel, user_has_cis_role,
    user_has_highschool_admin_role, get_field
)

from cis.models.highschool_administrator import HSAdministrator
from cis.models.highschool import HighSchool
from cis.models.term import Term
from cis.models.course import Campus
from cis.models.section import ClassSection, StudentRegistration
from cis.integrations.grades import grade_scale
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus

class class_export(forms.Form):
    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    term = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Term(s)'
    )

    highschool = forms.ModelMultipleChoiceField(
        queryset=None,
        label='High School(s)'
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

        self.fields['highschool'].queryset = HighSchool.objects.filter(
            status__iexact='active'
        ).order_by('name')

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

            if user_has_highschool_admin_role(self.request.user):
                school_admin = HSAdministrator.objects.get(user=self.request.user)
                highschools = school_admin.get_highschools()

                self.fields['highschool'].queryset = highschools

            # Populate the campus selector with only the campuses the
            # requesting user may process (superusers see all).
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)

        self.fields['term'].queryset = Term.objects.all().order_by('-code')

    def get_result(self, data, user=None):
        term_id = data['term']
        highschools = data.get('highschool')

        records = ClassSection.objects.select_related(
            'term', 'course', 'highschool', 'teacher__user'
        ).only(
            'id', 'class_number', 'section_number', 'instruction_mode', 'roster_status',
            'term__code', 'term__label',
            'course__name', 'course__title', 'course__credit_hours',
            'highschool__name',
            'teacher__user__last_name', 'teacher__user__first_name', 'teacher__user__email',
            'teacher__user__last_login'
        ).filter(
            term__id__in=term_id,
            highschool__in=highschools
        )

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        records = scope_report_by_campus(
            records, user, data.get('campus'), campus_path='course__campus')

        return records

    def run(self, task, data):
        # `task` is the ReportScheduler; task.created_by is the requesting user
        # (there is no request in the background task, so gate by the scheduler).
        records = self.get_result(data, user=getattr(task, 'created_by', None))
        section_ids = [record.id for record in records]

        student_registrations = StudentRegistration.objects.filter(
            class_section__id__in=section_ids
        ).values(
            'class_section', 'status'
        ).annotate(
            count=Count('class_section')
        )

        regis_summary = {}
        for student_registration in student_registrations:
            regis_summary[
                str(student_registration['class_section'])+'-'+student_registration['status']
            ] = student_registration['count']

        # Get grade list from the grades app (via the cis shim) and aggregate
        # grade counts. ``grade_scale()`` mirrors today's parsing, returning
        # ``['']`` for an empty setting and ``[]`` when grades is absent; the
        # strip/filter below collapses both to no grade columns, exactly as before.
        grade_list = [g.strip() for g in grade_scale() if g.strip()]

        grade_registrations = StudentRegistration.objects.filter(
            class_section__id__in=section_ids
        ).values(
            'class_section', 'grade'
        ).annotate(
            count=Count('class_section')
        )

        grade_summary = {}
        for grade_reg in grade_registrations:
            grade_summary[
                str(grade_reg['class_section']) + '-' + grade_reg['grade']
            ] = grade_reg['count']
            
        file_name = "class_sections.csv"
        fields = {
            'pk': 'ID',
            'term.label': "Term",
            'term.code': "Term Code",
            "course": "Course",
            'course.title': 'Title',
            "class_number": "Class No.",
            "section_number": "Section No.",
            'course.credit_hours': 'Credits',
            'highschool.name': 'High School',
            'highschool.hs_type_display': 'School Type',
            'teacher.user.last_name': 'Instructor Last Name',
            'teacher.user.first_name': 'Instructor First Name',
            "teacher.user.email": "Instructor Email",
            'teacher.user.last_login': 'Instructor Last Login',
            'instruction_mode': 'Instruction Mode',
            'roster_status': 'Roster Status',
        }

        status_list = []
        for k, v in StudentRegistration.STATUS_OPTIONS:
            status_list.append(v)

        result = []
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        writer.writerow(list(fields.values()) + status_list + grade_list)
        for record in records.iterator():
            row = []
            for key in fields.keys():
                row.append(
                    force_str(get_field(record, key))
                )

            for k, v in StudentRegistration.STATUS_OPTIONS:
                row.append(
                    regis_summary.get(
                        str(record.id) + "-" + k
                    )
                )

            for grade in grade_list:
                row.append(
                    grade_summary.get(
                        str(record.id) + "-" + grade
                    )
                )
            writer.writerow(row)
    
        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path
