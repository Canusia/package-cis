import io
import csv
import datetime

from django import forms
from django.urls import reverse_lazy
from django.http import HttpResponse
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.term import Term
from cis.models.student import StudentSupportingDocument
from cis.models.course import Campus
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus

class supporting_doc_export(forms.Form):

    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    term = forms.ModelChoiceField(
        queryset=None,
        label='Term'
    )

    uploaded_on_from = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class':'col-md-6 col-sm-12'}),
        input_formats=[('%m/%d/%Y')],
        required=False
    )

    uploaded_on_until = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class':'col-md-6 col-sm-12'}),
        required=False,
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

        self.fields['term'].queryset = Term.objects.all().order_by('-code')

        # Populate the campus selector with only the campuses the requesting
        # user may process (superusers see all prefixed campuses).
        if self.request:
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    def get_results(self, term, created_from, created_until):
        records = StudentSupportingDocument.objects.select_related(
            'student__user',
            'student__highschool',
            'term'
        ).filter(
            term__id__in=term
        )

        if created_from:
            records = records.filter(
                uploaded_on__gte=created_from
            )

        if created_until:
            records = records.filter(
                uploaded_on__lte=created_until
            )

        return records

    def get_result(self, data, user=None):
        created_from, created_until = None, None

        if data.get('uploaded_on_from')[0]:
            created_from = datetime.datetime.strptime(
                data.get('uploaded_on_from')[0],
                '%m/%d/%Y'
            )

        if data.get('uploaded_on_until')[0]:
            created_until = datetime.datetime.strptime(
                data.get('uploaded_on_until')[0],
                '%m/%d/%Y'
            )

        records = self.get_results(data['term'], created_from, created_until)

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        records = scope_report_by_campus(
            records, user, data.get('campus'),
            campus_path='student__studentregistration__class_section__course__campus',
            distinct=True)

        return records

    def run(self, task, data):
        records = self.get_result(data, user=getattr(task, 'created_by', None))

        media_storage = PrivateMediaStorage()

        result = []
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        path_prefix = f'reports/' + datetime.datetime.now().strftime('%Y/%m') + f'/{task.id}/'
        
        if data.get('export_type')[0] in ['download']:
            import os
            import zipfile
            from io import BytesIO

            ZIPFILE_NAME = f"supporting_docs_export_" + datetime.datetime.now().strftime('%Y_%m_%d') + ".zip"
            b =  BytesIO()

            # records = records[0:5]
            index = 1
            with zipfile.ZipFile(b, 'w') as zf:            
                for record in records:
                    index += 1
                    row = []

                    file_name = f'{record.student.user.last_name}_{record.student.user.first_name}_{record.student.user.id}_{index}.pdf'

                    row.append(record.id)
                    row.append(record.term)
                    row.append(record.uploaded_on)
                    row.append(record.description)
                    row.append(record.student.user.psid)
                    row.append(record.student.user.first_name)
                    row.append(record.student.user.last_name)
                    row.append(record.student.user.email)
                    row.append(record.student.highschool.name)

                    row.append(file_name)
                    writer.writerow(row)

                    fh = PrivateMediaStorage().open(record.media.name, "rb")
                    zf.writestr(file_name, bytes(fh.read()))


                # write export list file
                content = stream.getvalue()
                
                file_name = 'supporting_doc_exports.csv'
                zf.writestr(file_name, content)

            zf.close()

            response = HttpResponse(b.getvalue(), content_type="application/x-zip-compressed")
            response['Content-Disposition'] = f'attachment; filename={ZIPFILE_NAME}'
    
            path = media_storage.save(path_prefix+ZIPFILE_NAME, ContentFile(response.getvalue()))
            path = media_storage.url(path)

            return path
