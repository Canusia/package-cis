from django import forms
from django.urls import reverse_lazy
from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse
from django.core.files.base import ContentFile, File

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import export_to_excel, user_has_cis_role

from cis.backends.storage_backend import PrivateMediaStorage
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministratorPosition, HSPosition
)

class highschool_admin_password_reset(forms.Form):

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
        if request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

        self.helper.add_input(Submit('submit', 'Generate Export'))

        self.fields['positions'].queryset = HSPosition.objects.all().order_by('name')
        self.fields['highschools'].queryset = HighSchool.objects.filter(
            status__iexact='Active').order_by('name')

    def run(self, task, data):
        position_ids = data.get('positions', None)
        highschool_ids = data.get('highschools', None)

        records = HSAdministratorPosition.objects.filter(
            highschool__id__in=highschool_ids,
            position__id__in=position_ids
        )

        file_name = "highschool_administrators.csv"
        fields = {
            # 'pk': 'HighSchoolMemberPositionID',
            'highschool.name': 'High School',
            'highschool.status': 'High School Status',
            'highschool.hs_type_display': 'School Type',

            'hsadmin.user.last_name': 'Last Name',
            'hsadmin.user.first_name': 'First Name',
            'hsadmin.user.email': 'Email',

            'position.name': 'Position',
            'status': 'Status',
            'hsadmin.user.password_reset_link': 'Password Reset Link'
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
