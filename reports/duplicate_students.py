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

from cis.services import duplicate_students as dup


class duplicate_students(forms.Form):
    """Students who match each other under the tenant's duplicate-student
    rules — the same rules that block a duplicate signup, so the report and
    the application never disagree about what a duplicate is."""

    roles = []
    request = None

    COLUMNS = [
        'Group', 'Matched On', 'Canusia Id', 'User ID', 'Last Name',
        'First Name', 'Middle Name', 'Date of Birth', 'High School', 'Email',
        'Account Verified', 'Application Completed', 'Joined On',
    ]

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    @staticmethod
    def _matched_on(rule):
        return ', '.join(
            name.replace('_', ' ').capitalize() for name in rule['fields'])

    def get_rows(self, data=None):
        """One row per student per group. The matched values themselves
        (an SSN, notably) are never written — only which fields matched."""
        rows = []
        for number, (rule, students) in enumerate(dup.find_duplicate_groups(), 1):
            matched_on = self._matched_on(rule)
            for student in sorted(students, key=lambda s: s.user.date_joined):
                user = student.user
                rows.append([
                    number,
                    matched_on,
                    user.id,
                    user.psid or '',
                    user.last_name,
                    user.first_name,
                    user.middle_name or '',
                    user.date_of_birth.strftime('%m/%d/%Y') if user.date_of_birth else '',
                    student.highschool.name if student.highschool_id else '',
                    user.email,
                    'Yes' if student.account_verified else 'No',
                    'Yes' if user.psid else 'No',
                    user.date_joined.strftime('%m/%d/%Y'),
                ])
        return rows

    def run(self, task, data):
        file_name = "potential-dup-student-export.csv"

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')
        writer.writerow(self.COLUMNS)
        for row in self.get_rows(data):
            writer.writerow([force_str(value) for value in row])

        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path

    def run_report(self):
        ...
