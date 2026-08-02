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
    HSAdministratorPosition, HSPosition
)
from cis.models.teacher import Teacher, TeacherHighSchool

class teacher_password_reset(forms.Form):
    
    highschools = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Active High School(s)'
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
        
        self.fields['highschools'].queryset = HighSchool.objects.filter(
            status__iexact='Active'
        ).order_by('name')

    def run(self, task, data):
        highschool_ids = data.get('highschools', None)

        records = TeacherHighSchool.objects.filter(
            highschool__id__in=highschool_ids
        )
        
        file_name = "teacher_password_reset.csv"
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
            'teacher.user.email': 'Email',
            'teacher.user.first_name': 'First Name',
            'teacher.user.last_name': 'Last Name',
            'teacher.user.password_reset_link': 'Password Reset Link'
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