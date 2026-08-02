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

from cis.models.highschool import HighSchool
from cis.models.term import Term
from cis.models.section import ClassSection
from cis.models.teacher import TeacherCourseCertificate
from cis.models.course import Course

class teacher_course_certificate(forms.Form):
    
    highschools = forms.ModelMultipleChoiceField(
        queryset=None,
        label='High School(s)'
    )

    certificate_status = forms.MultipleChoiceField(
        choices=TeacherCourseCertificate.STATUS_OPTIONS,
        label='Course Certificate Status'
    )

    course = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False
    )

    terms = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        label='Taught Class(es) In'
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

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )
        
        self.fields['course'].queryset = Course.objects.all().order_by('name')
        self.fields['highschools'].queryset = HighSchool.objects.filter(status__iexact='active').order_by('name')
        self.fields['terms'].queryset = Term.objects.all().order_by('-code')

    def run(self, task, data):
        certificate_status = data['certificate_status']
        course = data.get('course')

        records = TeacherCourseCertificate.objects.select_related(
            'teacher_highschool__teacher__user',
            'teacher_highschool__highschool__district',
            'course'
        ).filter(
            status__in=certificate_status,
            teacher_highschool__highschool__id__in=data.get('highschools')
        ).order_by(
            'teacher_highschool__teacher__user__last_name', 'course__name'
        )

        if course:
            records = records.filter(
                course__id__in=course
            )

        if data.get('terms'):
            teacher_ids = ClassSection.objects.filter(
                term__id__in=data.get('terms')
            ).values_list('teacher__id', flat=True)

            records = records.filter(
                teacher_highschool__teacher__id__in=teacher_ids
            )

        file_name = "teacher_course_subject_count_export" + str(datetime.datetime.now()) + ".csv"
        fields = {
            'teacher_highschool.teacher.user.psid': 'EMPLID',
            'teacher_highschool.teacher.user.first_name': 'Teacher First Name',
            'teacher_highschool.teacher.user.last_name': 'Teacher Last Name',
            'teacher_highschool.teacher.user.email': 'Primary Email',
            'teacher_highschool.teacher.status': 'Teacher Status',
            'teacher_highschool.teacher.user.secondary_email': 'Secondary Email',
            'teacher_highschool.teacher.user.alt_email': 'Alt Email',
            'teacher_highschool.highschool': 'High School',
            'teacher_highschool.highschool.district': 'District',
            'course.name': 'Course',
            'since': 'Since',
            'status': 'Status'
        }

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        writer.writerow(fields.values())

        for record in records.iterator():
            row = []
            for key in fields.keys():
                try:
                    row.append(
                        force_str(get_field(record, key))
                    )
                except Exception:
                    row.append('error')

            writer.writerow(row)
        
        path = "reports/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path
