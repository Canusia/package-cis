import io, csv, datetime

from django import forms
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
 
# from cis.models.highschool import HighSchool
from cis.models.term import Term
from cis.models.section import ClassSection, Campus
from cis.models.teacher import Teacher, TeacherCourseCertificate
from cis.models.course import Course, Cohort

from pd_event.models import EventType, EventAttendee

class teacher_course_certificate_count(forms.Form):
    
    certificate_status = forms.MultipleChoiceField(
        choices=TeacherCourseCertificate.STATUS_OPTIONS,
        label='Course Certificate Status'
    )

    subject = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False
    )

    course = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False
    )

    # event_type = forms.ModelChoiceField(
    #     queryset=None,
    #     required=False,
    #     help_text='Choose to see last attended'
    # )

    roles = []
    request = None
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )
        
        self.fields['subject'].queryset = Cohort.objects.all().order_by('name')
        self.fields['course'].queryset = Course.objects.all().order_by('name')
        # self.fields['event_type'].queryset = EventType.objects.all().order_by('name')

    def run(self, task, data):
        certificate_status = data['certificate_status']
        subject = data.get('subject')
        course = data.get('course')

        # campus_ids = data.get('campus', None)

        records = TeacherCourseCertificate.objects.filter(
            status__in=certificate_status
        ).order_by(
            'teacher_highschool__teacher__user__last_name', 'course__name'
        )

        if subject:
            records = records.filter(
                course__cohort__id__in=subject
            )

        if course:
            records = records.filter(
                course__id__in=course
            )

        teacher_cohorts = {}
        for record in records:
            teacher_cohort = teacher_cohorts.get(record.teacher_highschool.teacher.user.psid, [])

            if record.course.cohort.name not in teacher_cohort:
                teacher_cohort.append(record.course.cohort.name)
            teacher_cohorts[record.teacher_highschool.teacher.user.psid] = teacher_cohort

        records = records.values('teacher_highschool__teacher').distinct()
        records = Teacher.objects.filter(
            id__in=records
        )
        file_name = "teacher_course_subject_count_export" + str(datetime.datetime.now()) + ".csv"
        fields = {
            'user.first_name': 'Teacher First Name',
            'user.last_name': 'Teacher Last Name',
            'user.psid': 'EMPLID',
            'active_highschools': 'High School',
            'active_highschool_districts': 'District',
            'principal_name': 'High School Principal',
            'principal_email': 'High School Principal Email',
            'user.secondary_email': 'High School Email',
            'user.email': 'Email',
            'user.username': 'Username',
            'user.primary_phone': 'Primary Phone'
        }

        result = []
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        event_type = None
        writer.writerow(list(fields.values()) + ['Subjects' , '# Subjects'])


        for record in records:
            row = []
            for key in fields.keys():
                try:
                    row.append(
                        force_str(get_field(record, key))
                    )
                except:
                    row.append('error')

            # row.append(teacher_cohorts.get(record.user.psid), [])
            row.append(','.join(teacher_cohorts.get(record.user.psid, [])))
            row.append(len(teacher_cohorts.get(record.user.psid, [])))
            
            writer.writerow(row)
        
        path = "reports/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path
