import io
import csv

from django import forms
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import get_field
from cis.models.term import Term
from cis.models.course import Campus
from cis.models.student import StudentRecommendation
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus
from cis.services.recommendation_fields import recommendation_export_fields

_CAMPUS_PATH = 'student__studentregistration__class_section__course__campus'


class recommendation_export(forms.Form):

    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    term = forms.ModelChoiceField(
        queryset=None,
        label='Registration Term',
        help_text=''
    )

    roles = []
    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'

        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)

        self.fields['term'].queryset = Term.objects.all().order_by('-code')

        self.helper.add_input(Submit('submit', 'Generate Export'))

    def get_result(self, data, user=None):
        records = StudentRecommendation.objects.select_related(
            'student__user',
            'student__highschool',
            'term'
        ).filter(
            term__id__in=data.get('term')
        )

        records = scope_report_by_campus(
            records, user, data.get('campus'),
            campus_path=_CAMPUS_PATH, distinct=True)

        return records

    #: Columns that come from the record itself and are the same for every
    #: tenant. The counselor's answers go between the two blocks.
    IDENTITY_COLUMNS = {
        'student.id': 'Canusia ID Number',
        'student.user.first_name': 'Student Legal First Name',
        'student.user.last_name': 'Student Legal Last Name',
        'student.user.middle_name': 'Middle Name or Initial',
        'student.highschool.name': 'High School',
    }

    SUBMISSION_COLUMNS = {
        'submitted_on': 'Submitted On',
        'submitted_by': 'Submitted By',

        'term.code': 'Term Code',
        'term.label': 'Term',
    }

    def column_map(self):
        """``{accessor: header}`` for the export, in column order.

        The answer columns follow the tenant's own recommendation form rather
        than a fixed list. The list used to be one tenant's Pennsylvania
        vocabulary, so every other tenant ran this report -- and CE staff do
        run it -- and got five permanently-empty columns and none of its own
        (ewu#49).
        """
        fields = dict(self.IDENTITY_COLUMNS)
        fields.update(recommendation_export_fields())
        fields.update(self.SUBMISSION_COLUMNS)
        return fields

    def run(self, task, data):
        records = self.get_result(data, user=getattr(task, 'created_by', None))

        file_name = "student-recommendation-export.csv"
        fields = self.column_map()

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        writer.writerow(list(fields.values()))
        for record in records.iterator():
            row = []
            for key in fields.keys():
                row.append(
                    force_str(get_field(record, key))
                )

            writer.writerow(row)

        path = "reports/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path

    def run_report(self):
        ...
