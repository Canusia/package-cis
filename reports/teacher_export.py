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
from cis.models.teacher import Teacher, TeacherHighSchool


class teacher_export(forms.Form):

    highschools = forms.ModelMultipleChoiceField(
        queryset=None,
        label='High School(s)'
    )

    status = forms.MultipleChoiceField(
        choices=Teacher.STATUS_OPTIONS,
        label='Teacher Status'
    )

    highschool_status = forms.MultipleChoiceField(
        choices=TeacherHighSchool.STATUS_OPTIONS,
        label='Teacher High School Status'
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
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

        self.fields['highschools'].queryset = HighSchool.objects.filter(status__iexact='active').order_by('name')
        self.fields['terms'].queryset = Term.objects.all().order_by('-code')

    def run(self, task, data):
        records = TeacherHighSchool.objects.select_related(
            'teacher__user',
            'highschool__district'
        ).filter(
            status__in=data.get('highschool_status'),
            highschool__id__in=data.get('highschools')
        ).order_by(
            'teacher__user__last_name'
        )

        if data.get('terms'):
            teacher_ids = ClassSection.objects.filter(
                term__id__in=data.get('terms')
            ).values_list('teacher__id', flat=True)

            records = records.filter(
                teacher__id__in=teacher_ids
            )

        file_name = "teacher_export_" + str(datetime.datetime.now().strftime('%Y%m%d_%H%M%S')) + ".csv"

        fields = {
            'teacher.user.psid': 'EMPLID',
            'teacher.user.first_name': 'Teacher First Name',
            'teacher.user.last_name': 'Teacher Last Name',
            'teacher.user.email': 'Primary Email',
            'teacher.status': 'Teacher Status',
            'teacher.user.secondary_email': 'Secondary Email',
            'teacher.user.alt_email': 'Alt Email',
            'teacher.user.last_login': 'Last Login',
            'highschool': 'High School',
            'highschool.district': 'District',
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
