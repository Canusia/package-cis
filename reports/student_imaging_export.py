import io, csv, datetime, time

from django import forms
from django.db.models import Q
from django.urls import reverse_lazy
from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.encoding import force_str
from django.http import HttpResponse
from django.core.files.base import ContentFile, File

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

# from cis.models.highschool import HighSchool
from cis.models.term import Term
from cis.models.course import Campus
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.customuser import CustomUser
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus

class student_imaging_export(forms.Form):

    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    account_verified_on_from = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class':'col-md-6 col-sm-12'}),
        input_formats=[('%m/%d/%Y')]
    )

    account_verified_on_until = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class':'col-md-6 col-sm-12'}),
        input_formats=[('%m/%d/%Y')]
    )

    export_type = forms.ChoiceField(
        choices=[
            ('download', 'Download Zip File'),
            # ('download_encrypted', 'Download Encrypted Zip File'),
            # ('export_to_imaging', 'Export to Imaging'),
            # ('export_encrypted_to_imaging', 'Export to Imaging - Encrypted'),
        ]
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
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    def get_results(self, created_from, created_until):
        records = Student.objects.filter(
            account_verified_on__gte=created_from,
            account_verified_on__lte=created_until
        ).exclude(
            highschool__isnull=True
        )

        return records

    def get_result(self, data, user=None):
        created_from = datetime.datetime.strptime(
            data.get('account_verified_on_from')[0],
            '%m/%d/%Y'
        )
        created_until = datetime.datetime.strptime(
            data.get('account_verified_on_until')[0],
            '%m/%d/%Y'
        )

        records = self.get_results(created_from, created_until)

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        records = scope_report_by_campus(
            records, user, data.get('campus'),
            campus_path='studentregistration__class_section__course__campus',
            distinct=True)

        return records

    def run(self, task, data):
        records = self.get_result(data, user=getattr(task, 'created_by', None))

        media_storage = PrivateMediaStorage()

        result = []
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        path_prefix = f'reports/' + datetime.datetime.now().strftime('%Y/%m') + f'/{task.id}/'
        
        if data.get('export_type')[0] in ['download', 'download_encrypted']:
            import os
            import zipfile
            from io import BytesIO

            ZIPFILE_NAME = f"imaging_export_" + datetime.datetime.now().strftime('%Y_%m_%d') + ".zip"
            b =  BytesIO()

            
            # records = records[0:5]
            with zipfile.ZipFile(b, 'w') as zf:            
                for record in records:
                    row = []

                    row.append(record.id)
                    # row.append(record.term)
                    # row.append(record.uploaded_on)
                    # row.append(record.description)
                    row.append(record.user.psid)
                    row.append(record.user.first_name)
                    row.append(record.user.last_name)
                    row.append(record.user.email)
                    row.append(record.highschool.name)
                                       
                    file_name = f'{record.user.last_name}_{record.user.first_name}_{record.user.id}.pdf'
                    
                    writer.writerow(row)

                    pdf = record.as_pdf()

                    zf.writestr(file_name, pdf)

                content = stream.getvalue()
                file_name = 'supporting_doc_exports.csv'
                zf.writestr(file_name, content)

            zf.close()

            response = HttpResponse(b.getvalue(), content_type="application/x-zip-compressed")
            response['Content-Disposition'] = f'attachment; filename={ZIPFILE_NAME}'
    
            path = media_storage.save(path_prefix+ZIPFILE_NAME, ContentFile(response.getvalue()))
            path = media_storage.url(path)

            return path
