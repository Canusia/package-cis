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
from cis.models.teacher import TeacherCourseCertificate


class teacher_certificates(forms.Form):

    use_as_datasource = True
    datasource_descriptor = 'Instructors from the Teacher Course Certificates report.'
    email_column = 'email'
    name_columns = ['FirstName', 'LastName']

    window_days = forms.IntegerField(
        required=False,
        min_value=1,
        label='Expiring Within (days)',
        help_text='Optional. Leave blank to include all certificates; enter a '
                  'number of days to limit to those due within that window.')

    highschools = forms.ModelMultipleChoiceField(
        queryset=None,
        required=False,
        label='High School(s)')

    certificate_status = forms.MultipleChoiceField(
        choices=TeacherCourseCertificate.STATUS_OPTIONS,
        required=False,
        label='Course Certificate Status')

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
                'report:run_report', args=[request.GET.get('report_id')])
        self.fields['highschools'].queryset = HighSchool.objects.filter(
            status__iexact='active').order_by('name')

    def filtered_queryset(self, window_days=None, highschools=None, statuses=None):
        """Teacher course certificates, optionally limited to a due-date window.

        When window_days is falsy, ALL certificates are returned. Otherwise the
        result is limited to certificates whose renewal_due_date (renewal_required_by
        else expires_on) falls within window_days of today, via the model's
        due_within_q helper (so the filter stays a queryset).
        """
        records = TeacherCourseCertificate.objects.select_related(
            'teacher_highschool__teacher__user',
            'teacher_highschool__highschool__district',
            'course',
        )

        if window_days:
            records = records.filter(
                TeacherCourseCertificate.due_within_q(window_days))
        if highschools:
            records = records.filter(
                teacher_highschool__highschool__id__in=highschools)
        if statuses:
            records = records.filter(status__in=statuses)

        return records.order_by('expires_on', 'renewal_required_by')

    def recipient_columns(self):
        return {'first_name': 'FirstName', 'last_name': 'LastName', 'email': 'email'}

    def get_recipients(self, data):
        records = self.filtered_queryset(
            window_days=None,
            highschools=data.get('highschools'),
            statuses=data.get('certificate_status'))
        rows = []
        seen = set()
        for cert in records.iterator():
            u = cert.teacher_highschool.teacher.user
            if not u.email or u.email in seen:
                continue
            seen.add(u.email)
            rows.append({
                'FirstName': u.first_name,
                'LastName': u.last_name,
                'email': [u.email],
            })
        return rows

    def run(self, task, data):
        raw = data.get('window_days')
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        try:
            window_days = int(raw) if raw not in (None, '') else None
        except (TypeError, ValueError):
            window_days = None

        records = self.filtered_queryset(
            window_days=window_days,
            highschools=data.get('highschools'),
            statuses=data.get('certificate_status'),
        )

        file_name = "teacher_certificates_export" + str(datetime.datetime.now()) + ".csv"
        fields = {
            'teacher_highschool.teacher.user.psid': 'EMPLID',
            'teacher_highschool.teacher.user.first_name': 'Teacher First Name',
            'teacher_highschool.teacher.user.last_name': 'Teacher Last Name',
            'teacher_highschool.teacher.user.email': 'Primary Email',
            'teacher_highschool.highschool': 'High School',
            'teacher_highschool.highschool.district': 'District',
            'course.name': 'Course',
            'status': 'Status',
            'renewal_due_date': 'Renewal Due',
            'expires_on': 'Expires On',
            'last_renewed_on': 'Last Renewed On',
        }

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')
        writer.writerow(fields.values())

        for record in records.iterator():
            row = []
            for key in fields.keys():
                try:
                    row.append(force_str(get_field(record, key)))
                except Exception:
                    row.append('error')
            writer.writerow(row)

        path = "reports/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()
        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)
        return path
