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
from cis.models.section import ClassSection
from cis.models.course import Campus
import importlib.util
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.models import FutureSection, FutureCourse
else:
    from future_sections.models import FutureSection, FutureCourse

from cis.models.teacher import TeacherCourseCertificate
from cis.models.highschool_administrator import (
    HSAdministratorPosition, HSPosition
)
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus

class pending_future_classes_courses(forms.Form):
    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

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

            # Populate the campus selector with only the campuses the
            # requesting user may process (superusers see all).
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)

        self.fields['academic_year'].queryset = AcademicYear.objects.all().order_by('-name')

    def get_result(self, data, user=None):
        academic_year_id = data['academic_year'][0]

        from cis.settings.future_sections import future_sections as fs_settings

        fs_setting_config = fs_settings.from_db()

        received_records = FutureCourse.objects.filter(
            academic_year__id=academic_year_id
        ).values_list('teacher_course__certificate_id', flat=True)

        records = TeacherCourseCertificate.objects.filter(
            course__status__in=fs_setting_config.get('course_status'),
            status__in=fs_setting_config.get('teacher_course_status')
        ).exclude(
            certificate_id__in=received_records
        )

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        records = scope_report_by_campus(
            records, user, data.get('campus'), campus_path='course__campus')

        return records

    def run(self, task, data):
        import datetime

        # `task` is the ReportScheduler; task.created_by is the requesting user
        # (there is no request in the background task, so gate by the scheduler).
        records = self.get_result(data, user=getattr(task, 'created_by', None))

        file_name = "pending_future_class_courses-" + str(datetime.datetime.now()) + ".csv"
        fields = {
            'pk': 'ID',
            'teacher_highschool.highschool': 'School',
            'teacher_highschool.highschool.hs_type_display': 'School Type',
            'teacher_highschool.teacher.user.last_name': 'Teacher Last Name',
            'teacher_highschool.teacher.user.first_name': 'Teacher First Name',
            'course.name': 'Course Name',
            'status': 'Status',
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
