"""Course-type gate: which college sections a student may see, by the course
types their high school is approved for (HighSchoolCourseType).

Stored in the Setting model under key ``cis.settings.course_type_gate`` as::

    {
      'enabled': False,                    # off = today's behavior everywhere
      'applies_to': 'college_sections',    # or 'all_sections'
      'empty_means': 'nothing',            # school with no approvals sees ...
      'no_highschool_means': 'everything', # student with no high school sees ...
      'allow_create_from_tab': False,      # "New course type" on the HS tab
    }

Everything ships off; each tenant turns it on in its own instance. Read
through the classmethods, never the Setting row directly: an unset key falls
back to DEFAULTS.
"""
from django import forms
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.settings import Setting


DEFAULTS = {
    'enabled': False,
    'applies_to': 'college_sections',
    'empty_means': 'nothing',
    'no_highschool_means': 'everything',
    'allow_create_from_tab': False,
}

APPLIES_TO_OPTIONS = (
    ('college_sections', 'College sections only (sections with no high school)'),
    ('all_sections', 'All sections'),
)
SEES_OPTIONS = (
    ('nothing', 'No gated sections'),
    ('everything', 'Every gated section (no filter)'),
)


class SettingForm(forms.Form):
    enabled = forms.BooleanField(
        required=False,
        label='Limit sections to approved course types',
        help_text=("Students only see sections whose course type their high "
                   "school is approved for (High School > Course Types tab)."),
    )
    applies_to = forms.ChoiceField(
        choices=APPLIES_TO_OPTIONS,
        label='Applies To',
    )
    empty_means = forms.ChoiceField(
        choices=SEES_OPTIONS,
        label='A School With No Approved Course Types Sees',
    )
    no_highschool_means = forms.ChoiceField(
        choices=SEES_OPTIONS,
        label='A Student With No High School Sees',
    )
    allow_create_from_tab = forms.BooleanField(
        required=False,
        label='Allow Creating Course Types From the High School Tab',
        help_text=('Off: course types are created only on the Course Types page, '
                   'because the SIS importer matches on their codes.'),
    )

    def _to_python(self):
        return {
            'enabled': self.cleaned_data.get('enabled', False),
            'applies_to': self.cleaned_data['applies_to'],
            'empty_means': self.cleaned_data['empty_means'],
            'no_highschool_means': self.cleaned_data['no_highschool_means'],
            'allow_create_from_tab': self.cleaned_data.get('allow_create_from_tab', False),
        }


class course_type_gate(SettingForm):
    key = str(__name__)

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request
        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')])
        self.helper.add_input(Submit('submit', 'Save Setting'))

    @classmethod
    def get_config(cls):
        try:
            stored = Setting.objects.get(key=cls.key).value or {}
        except Setting.DoesNotExist:
            stored = {}
        return {**DEFAULTS, **stored}

    @classmethod
    def from_db(cls):
        return cls.get_config()

    @classmethod
    def is_enabled(cls):
        return bool(cls.get_config().get('enabled'))

    @classmethod
    def allow_create_from_tab(cls):
        return bool(cls.get_config().get('allow_create_from_tab'))

    def install(self):
        Setting.install_defaults(self.key, dict(DEFAULTS))
