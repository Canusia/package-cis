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
from cis.models.customuser import CustomUser

class duplicate_students(forms.Form):
    

    roles = []
    request = None
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        # self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        # for cis users only show their campus
        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )
        
    def get_result(self, data):
        # filter students who have same first name, last name, and date of birth but different email
        records = CustomUser.objects.raw('''
            SELECT u1.*
            FROM cis_customuser u1
            JOIN cis_customuser u2
            ON u1.first_name = u2.first_name
            AND u1.last_name = u2.last_name
            AND u1.email <> u2.email
            WHERE u1.id <> u2.id
            ORDER BY u1.last_name, u1.first_name
        ''')
        return records

    def run(self, task, data):
        records = self.get_result(data)
        
        file_name = "potential-dup-student-export.csv"
        fields = {

            'id': 'Canusia Id',
            'psid': 'User ID',

            'first_name': 'First Name',
            'last_name': 'Last Name',
            'middle_name': 'Middle Name',
            'suffix': 'Suffix',
            'preferred_name': 'Preferred Name',
            'email': 'Email'
        }
        
        result = []
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        writer.writerow(list(fields.values()))
        for record in records:
            row = []
            for key in fields.keys():
                
                row.append(
                    force_str(get_field(record, key))
                )

            writer.writerow(row)

        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path

    def run_report(self):
        ...
