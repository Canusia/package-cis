"""Whether a recommendation is gated on the student's own grade level.

Stored in the Setting model under key ``cis.settings.recommendation_policy``::

    {'require_grade_level_match': bool}

``Course.registration_eligibility`` marks a grade as needing a recommendation by
suffixing it with ``*`` — FR*, SO*, JR*, SR*. With this setting ON (the default)
a recommendation is required only when the student's *own* grade carries the
asterisk. With it OFF the course-level flag still applies, but the grade match
does not: any course that asterisks any grade requires a recommendation from
everyone, and a course with no asterisk at all still requires none.

An absent key reads as True, so a deployment that has never touched this setting
behaves exactly as it did before it existed.
"""
from django import forms
from django.http import JsonResponse
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.settings import Setting

_FIELD = 'require_grade_level_match'


class SettingForm(forms.Form):
    require_grade_level_match = forms.BooleanField(
        required=False,
        label="Require the student's grade level to match",
        help_text='On: a recommendation is required only when the course marks '
                  "the student's own grade with an asterisk. Off: any course "
                  'that marks any grade requires a recommendation from every '
                  'student. Courses that mark no grade never require one '
                  'either way.')

    def _to_python(self):
        return {_FIELD: bool(self.cleaned_data.get(_FIELD))}


class recommendation_policy(SettingForm):
    # Pinned literal (NOT str(__name__)): the Setting DB key must stay stable
    # regardless of how the module is imported.
    key = 'cis.settings.recommendation_policy'

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.helper = FormHelper()
        self.helper.form_method = 'POST'
        self.helper.form_action = reverse_lazy(
            'setting:run_record', args=[request.GET.get('report_id')]) if request else ''
        self.helper.add_input(Submit('submit', 'Save Setting'))

    @classmethod
    def get_config(cls):
        """Raw stored dict ({} if unset)."""
        try:
            return Setting.objects.get(key=cls.key).value or {}
        except Setting.DoesNotExist:
            return {}

    @classmethod
    def grade_match_required(cls):
        """The resolved boolean; an absent key defaults to True.

        Deliberately not named after the form field: Django's
        DeclarativeFieldsMetaclass pops declared fields off the class, and a
        classmethod sharing the field's name reads as a collision.
        """
        return bool(cls.get_config().get(_FIELD, True))

    @classmethod
    def from_db(cls):
        """Form-population initials (checkbox state)."""
        return {_FIELD: cls.grade_match_required()}

    def install(self):
        # Guarded, not unconditional: register_settings calls install() whenever
        # the SettingRecord registry row is missing, which can happen while the
        # Setting row itself holds a configured value. Overwriting here would
        # silently discard an admin's choice on an ordinary boot.
        if Setting.objects.filter(key=self.key).exists():
            return
        Setting.objects.create(key=self.key, value={_FIELD: True})

    def run_record(self):
        value = self._to_python()
        setting, created = Setting.objects.get_or_create(
            key=self.key, defaults={'value': value})
        if not created:
            setting.value = value
            setting.save()
        return JsonResponse({'message': 'Successfully saved settings',
                             'status': 'success'})
