import io, csv, xlsxwriter

from django import forms
from django.urls import reverse_lazy
from django.forms import ValidationError
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from django.utils.encoding import force_str
from django.core.files.base import ContentFile, File
from django.template.loader import get_template

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import (
    export_to_excel, user_has_cis_role,
    user_has_highschool_admin_role, get_field
)

from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministratorPosition, HSPosition, HSAdministrator
)

class highschool_admin_missing_role(forms.Form):   

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
    
    def run(self, task, data):
    
        
        records = HSAdministratorPosition.objects.filter()
        records = HSAdministrator.objects.filter().exclude(
            id__in=records.values_list('hsadmin_id', flat=True)
        )

        file_name = "highschool_administrators_missing_role.csv"
        fields = {
            'user.last_name': 'Last Name',
            'user.first_name': 'First Name',
            'user.email': 'Email',
            'user.primary_phone': 'Phone',
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