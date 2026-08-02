import io, csv

from django import forms
from django.urls import reverse_lazy
from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.encoding import force_str
from django.core.files.base import ContentFile, File

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import (
    export_to_excel, user_has_cis_role,
    user_has_highschool_admin_role, get_field
)
 
# from cis.models.highschool import HighSchool
from cis.models.term import AcademicYear, Term
from cis.models.section import ClassSection, Campus
import importlib.util
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.models import FutureSection, FutureCourse, FutureProjection
else:
    from future_sections.models import FutureSection, FutureCourse, FutureProjection

from cis.models.teacher import TeacherCourseCertificate
from cis.models.highschool_administrator import (
    HSAdministratorPosition, HSPosition
)

class started_future_classes(forms.Form):
    academic_year = forms.ModelChoiceField(
        queryset=None
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
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )
        
        self.fields['academic_year'].queryset = AcademicYear.objects.all().order_by('-name')

    def run(self, task, data):
        academic_year_id = data['academic_year'][0]
        
        import datetime
        from cis.settings.future_sections import future_sections as fs_settings
        
        fs_setting_config = fs_settings.from_db()

        records = FutureProjection.objects.filter(
            academic_year__id=academic_year_id
        )
        
        file_name = "future_courses_started-" + str(datetime.datetime.now()) + ".csv"
        
        fields = {
            # 'pk': 'HighSchoolMemberPositionID',
            'academic_year.name': 'Academic Year',

            'highschool.name': 'School',
            'confirmed_administrators': 'Confirmed Administrators',
            'confirmed_class_sections': 'Confirmed Class Sections',
            
            'highschool.status': 'School Status',
            'highschool.hs_type_display': 'School Type',
            'highschool.code': 'CEEB Code',
            'highschool.address1': 'Address1',
            'highschool.address2': 'Address2',
            'highschool.city': 'City',
            'highschool.state': 'State',
            'highschool.postal_code': 'Zip',
            'highschool.primary_phone': 'Phone'
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
