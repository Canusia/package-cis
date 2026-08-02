import io
import csv
import datetime

from django import forms
from django.urls import reverse_lazy
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import user_has_highschool_admin_role

from cis.models.student import Student, ParentConsent
from cis.models.highschool_administrator import HSAdministrator

from cis.models.term import Term
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, Campus, StudentRegistration

class missing_parent_consent(forms.Form):
    term = forms.ModelChoiceField(
        queryset=None
    )

    highschool = forms.ModelMultipleChoiceField(
        queryset=None,
        label='High School(s)'
    )

    # campus = forms.ModelMultipleChoiceField(
    #     queryset=None,
    #     label='Campus'
    # )

    status = forms.MultipleChoiceField(
        choices=StudentRegistration.STATUS_OPTIONS,
        label='Registration Status'
    )

    roles = []
    request = None
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        # self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        self.fields['highschool'].queryset = HighSchool.objects.filter(
            status__iexact='active'
        ).order_by('name')

        # for cis users only show their campus
        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

            if user_has_highschool_admin_role(self.request.user):
                school_admin = HSAdministrator.objects.get(user=self.request.user)
                highschools = school_admin.get_highschools()

                self.fields['highschool'].queryset = HighSchool.objects.filter(
                    id__in=highschools.values_list('id', flat=True)
                )

        self.fields['term'].queryset = Term.objects.all().order_by('-code')

    def run(self, task, data):
        term_id = data.get('term', None)
        highschool_id = data.get('highschool')

        file_name = "missing_parent_consent" + str(datetime.datetime.now()) + ".csv"

        # get students who are applied or approved with eager loading
        distinct_applied_registrations = StudentRegistration.objects.select_related(
            'student__user',
            'student__highschool',
            'class_section__term'
        ).filter(
            status__in=data.get('status'),
            class_section__term__id__in=term_id,
            class_section__highschool__id__in=highschool_id
        ).distinct('student')

        # Prefetch all signed consents for these students and terms to avoid N+1
        student_ids = [r.student_id for r in distinct_applied_registrations]
        signed_consents = set(
            ParentConsent.objects.filter(
                student_id__in=student_ids,
                term_id__in=term_id,
                signed_on__isnull=False
            ).values_list('student_id', 'term_id')
        )

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        writer.writerow(
            [
                'Student First Name',
                'Student Last Name',
                'Student High School',
                'Student Email',
                'Student Parent First Name',
                'Student Parent Last Name',
                'Student Parent Email',
                'Consent Url',
            ]
        )

        # get distinct high schools in all registrations
        for registration in distinct_applied_registrations.iterator():
            student = registration.student
            term_id_val = registration.class_section.term.id

            # Check consent using prefetched data instead of calling has_signed()
            if (student.id, term_id_val) in signed_consents:
                continue

            row = [
                student.user.first_name,
                student.user.last_name,
                str(student.highschool) if student.highschool else '',
                student.user.email,
                student.parent_first_name,
                student.parent_last_name,
                student.parent_email,
                ParentConsent.get_url(student.id, term_id_val),
            ]

            writer.writerow(row)
        
        if not data.get('file_name'):
            path = "reports/" + str(task.id) + "/" + file_name
        else:
            path = data.get('file_name')

        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path
