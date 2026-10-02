from django import forms
from django.urls import reverse_lazy
from django.forms import ValidationError
from django.utils.translation import gettext_lazy as _

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.utils import export_to_excel, user_has_cis_role

from cis.models.highschool import HighSchool
from cis.highschool_scope import scope_highschools

class highschool_export(forms.Form):

    highschool_status = forms.MultipleChoiceField(
        choices=HighSchool.STATUS_OPTIONS,
        label='High School Status'
    )

    # highschools = forms.ModelMultipleChoiceField(
    #     queryset=None,
    #     label='High School(s)'
    # )

    roles = []
    request = None
    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'report:run_report', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Generate Export'))

        # self.fields['highschools'].queryset = HighSchool.objects.all().order_by('name')

    def run_report(self):
        highschool_status = self.cleaned_data.get('highschool_status', None)
        file_name = "highschools.csv"

        try:
            from cis.views.highschool import filter_by_link_status
            from django.db.models import Q
            records = scope_highschools(
                HighSchool.objects.all(), user=self.request.user)
            q = Q()
            for st in highschool_status:
                q |= Q(pk__in=filter_by_link_status(
                    HighSchool.objects.all(), st).values('pk'))
            records = records.filter(q).order_by('name')

            fields = {
                # 'pk': 'HighSchoolMemberPositionID',
                'name': 'High School',
                'code': 'CEEB Code',
                'sau': 'SAU',
                'address1': 'Address1',
                'address2': 'Address2',
                'city': 'City',
                'state': 'State',
                'postal_code': 'Zip',
                'primary_phone': 'Phone',
                'district.name': 'County',
                'status': 'Status'
            }
        except Exception as e:
            print(e)

        return export_to_excel(
            file_name,
            records,
            fields
        )
