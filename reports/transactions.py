import io
import csv
import datetime

from django import forms
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import get_field
from student_transactions.models import StudentTransaction
from cis.models.term import Term
from cis.models.course import Campus
from cis.campus_gate import get_accessible_campuses, scope_report_by_campus


class transactions(forms.Form):

    campus = forms.ModelMultipleChoiceField(
        queryset=Campus.objects.none(), required=True, label='Campus',
    )

    term = forms.ModelChoiceField(
        queryset=None,
        label='Registration Term',
        help_text=''
    )

    t_type = forms.MultipleChoiceField(
        choices=StudentTransaction.TRANSACTION_TYPES,
        label='Transaction Type(s)',
        widget=forms.CheckboxSelectMultiple
    )

    payment_type = forms.MultipleChoiceField(
        choices=StudentTransaction.PAYMENT_TYPES + StudentTransaction.REFUND_TYPES + StudentTransaction.SCHOLARSHIP_TYPES,
        label='Payment Type(s)',
        required=False,
        widget=forms.CheckboxSelectMultiple
    )

    created_on_from = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class': 'col-md-6 col-sm-12'}),
        required=False,
        input_formats=[('%m/%d/%Y')]
    )

    created_on_until = forms.DateField(
        widget=forms.DateInput(format='%m/%d/%Y', attrs={'class': 'col-md-6 col-sm-12'}),
        required=False,
        input_formats=[('%m/%d/%Y')]
    )

    roles = []
    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        self.fields['term'].queryset = Term.objects.all().order_by('-code')

        if self.request:
            self.fields['campus'].queryset = get_accessible_campuses(
                self.request.user)
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    def get_result(self, data, user=None):
        term_id = data.get('term')

        records = StudentTransaction.objects.select_related(
            'student__user',
            'student__highschool',
            'term'
        ).filter(
            term__id__in=term_id,
            t_type__in=data.get('t_type')
        )

        # Campus gate: filter to the selected campus(es), constrained to the
        # ce requester's processable campuses (superusers/non-ce as-is).
        records = scope_report_by_campus(
            records, user, data.get('campus'),
            campus_path='student__studentregistration__class_section__course__campus',
            distinct=True)

        if data.get('created_on_from')[0]:
            created_from = datetime.datetime.strptime(
                data.get('created_on_from')[0],
                '%m/%d/%Y'
            )
            records = records.filter(
                created_on__gte=created_from
            )

        if data.get('created_on_until')[0]:
            created_until = datetime.datetime.strptime(
                data.get('created_on_until')[0],
                '%m/%d/%Y'
            )
            records = records.filter(
                created_on__lt=created_until
            )

        if data.get('payment_type'):
            records = records.filter(
                label__in=data.get('payment_type')
            )

        return records

    def run(self, task, data):
        records = self.get_result(data, user=getattr(task, 'created_by', None))

        file_name = "student-transaction-export_" + datetime.datetime.now().strftime('%Y_%m_%d') + ".csv"
        fields = {
            'student.id': 'PASS ID',
            'student.user.first_name': 'First Name',
            'student.user.last_name': 'Last Name',
            'student.middle_name': 'Middle Name',
            'student._gender': 'Gender',

            'student.highschool.name': 'High School',

            'student.highschool': 'High School',
            'student.highschool.country.name': 'Country',
            'student.user.email': 'Email',
            'student.gender': 'Gender',
            'student.user.primary_phone': 'Cell Phone',

            'student.parent_first_name': 'Parent 1 First Name',
            'student.parent_last_name': 'Parent 1 Last Name',
            'student.parent_email': 'Parent 1 Email',
            'student.parent_phone': 'Parent 1 Phone',

            'student.current_student_balance': 'Student Current Balance',
            'student.current_school_balance': 'School Current Balance',

            'term': 'Term',
            'amount': 'Amount',
            'sexy_label': 'Label',
            'description': 'Description',
            'created_on': 'Created On',

            'check_number': 'Check Number',
            'check_date': 'Check Date',

            'registration': 'Registration'
        }

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

        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path

    def run_report(self):
        ...
