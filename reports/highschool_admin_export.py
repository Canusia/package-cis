from django import forms
from django.urls import reverse_lazy
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import export_to_excel
from cis.reports.datasource_mixin import ReportDataSourceMixin

from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministratorPosition, HSPosition
)

class highschool_admin_export(ReportDataSourceMixin, forms.Form):

    datasource_descriptor = 'High school administrators, by school and position.'
    email_column = 'email'
    name_columns = ['FirstName', 'LastName']
    datasource_fields = {
        'FirstName': 'hsadmin.user.first_name',
        'LastName': 'hsadmin.user.last_name',
        'email': 'hsadmin.user.email',
        'Phone': 'hsadmin.user.primary_phone',
        'HighSchool': 'highschool.name',
        'CEEBCode': 'highschool.code',
        'SchoolType': 'highschool.hs_type_display',
        'Position': 'position.name',
        'AdministratorStatus': 'status',
    }

    highschools = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Active High School(s)'
    )

    positions = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Position(s)'
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

        if request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )
        
        self.fields['positions'].queryset = HSPosition.objects.all().order_by('name')
        self.fields['highschools'].queryset = HighSchool.objects.filter(
            status__iexact='Active'
        ).order_by('name')

    def recipient_queryset(self, data):
        records = HSAdministratorPosition.objects.select_related(
            'hsadmin__user', 'highschool', 'position')
        highschool_ids = data.get('highschools')
        position_ids = data.get('positions')
        if highschool_ids:
            records = records.filter(highschool__id__in=highschool_ids)
        if position_ids:
            records = records.filter(position__id__in=position_ids)
        return records

    def run(self, task, data):
        position_ids = data.get('positions', None)
        highschool_ids = data.get('highschools', None)

        records = HSAdministratorPosition.objects.select_related(
            'highschool',
            'hsadmin__user',
            'position'
        ).filter(
            highschool__id__in=highschool_ids,
            position__id__in=position_ids
        )
        
        file_name = "highschool_administrators.csv"
        fields = {
            # 'pk': 'HighSchoolMemberPositionID',
            'highschool.name': 'High School',
            'highschool.status': 'High School Status',
            'highschool.hs_type_display': 'School Type',
            'highschool.code': 'CEEB Code',
            'highschool.address1': 'Address1',
            'highschool.address2': 'Address2',
            'highschool.city': 'City',
            'highschool.state': 'State',
            'highschool.postal_code': 'Zip',
            'highschool.primary_phone': 'Phone',
            'highschool.sau': 'SAU',

            'hsadmin.user.last_name': 'Last Name',
            'hsadmin.user.first_name': 'First Name',
            'hsadmin.user.email': 'Email',
            'hsadmin.user.primary_phone': 'Phone',

            'position.name': 'Position',
            'status': 'Administrator Status'
        }

        http_response = export_to_excel(
            file_name,
            records,
            fields
        )

        path = "reports/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(http_response.content))
        path = media_storage.url(path)

        return path