import io, csv, json

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
    from future_sections.future_sections.models import FutureSection, FutureCourse
else:
    from future_sections.models import FutureSection, FutureCourse

class future_classes(forms.Form):
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

        records = FutureCourse.objects.filter(
            academic_year__id=academic_year_id
        )

        from cis.settings.future_sections import future_sections as fs_settings
        fs_config = fs_settings.from_db()

        form_settings = fs_settings.from_db()
        try:
            form_labels = json.loads(form_settings.get('form_field_messages', '{}'))
        except:
            form_labels = {}

        file_name = "future_class_sections-" + str(datetime.datetime.now()) + ".csv"
        fields = {
            'pk': 'ID',
            'started_on': 'Added On',
            'future_course.academic_year': 'Academic Year',
            'teacher_course.teacher_highschool.highschool': 'High School',
            'teacher_course.teacher_highschool.highschool.code': 'High School CEEB',
            'teacher_course.teacher_highschool.highschool.hs_type_display': 'School Type',
            'teacher_course.teacher_highschool.teacher.user.last_name': 'Teacher Last Name',
            'teacher_course.teacher_highschool.teacher.user.first_name': 'Teacher First Name',
            'teacher_course.course.name': 'Course Name',
            'teaching_or_not': 'Offering Course',
        }
        
        if records:
            additional_data = records[0].additional_fields()
        else:
            additional_data = []
    
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        # write term labels
        additional_data_labels = []
        for field in additional_data:
            additional_data_labels.append(
                form_labels.get(field, {}).get('label', field)
            )

        writer.writerow(list(fields.values()) + additional_data_labels)

        for record in records:
            row = []
            
            for key in fields.keys():
                row.append(
                    force_str(get_field(record, key))
                )

            if record.teaching_or_not.lower() == 'yes':                
                for index, section_info in enumerate(record.section_info.get('sections', [])):
                    crs_row = list(row)

                    for k in additional_data:
                        crs_row.append(record.get_by_property(index, k))

                    writer.writerow(crs_row)
            else:
                writer.writerow(row)
        
        path = "reports/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path
