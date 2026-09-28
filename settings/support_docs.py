"""CE-configurable support-document settings (single, merged setting).

Stored in the Setting model under key ``cis.settings.support_docs`` as::

    {
      'types':    [...],            # document types (upload dropdown)
      'statuses': [...],            # document statuses (bulk-action dropdown)
      'email_enabled': 'Yes'|'No',  # send email when a doc's status changes
      'status_change_email_subject': '...',
      'status_change_email': '...', # Django-template body, {{placeholders}}
      'document_check_registration_statuses': [...],  # StudentRegistration
                                    # statuses whose courses still need docs
    }

Replaces the earlier split support_doc_types / support_doc_statuses settings;
``install()`` migrates their values and removes them.
"""
from django import forms
from django.http import JsonResponse
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from ..models.settings import Setting


_OLD_KEYS = ['cis.settings.support_doc_types', 'cis.settings.support_doc_statuses']


#: Registration statuses whose courses still need supporting documents, used
#: until CE saves its own choice (#42). Closed states -- dropped, withdrawn,
#: not_approved, denied_registration, duplicate -- are left out, as is the
#: limbo state 'app not processed'.
DEFAULT_DOCUMENT_CHECK_REGISTRATION_STATUSES = [
    'applied', 'approved', 'missing_prereq', 'pending_registration',
    'registered', 'enrolled',
]


def _lines_to_list(raw):
    return [line.strip() for line in (raw or '').splitlines() if line.strip()]


class SettingForm(forms.Form):

    YES_NO = [('Yes', 'Yes'), ('No', 'No')]

    types = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 6}),
        label='Support Document Types',
        help_text='Enter one document type per line.',
    )

    statuses = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 6}),
        label='Support Document Statuses',
        help_text='Enter one document status per line.',
    )

    email_enabled = forms.ChoiceField(
        choices=YES_NO,
        label='Email on Status Change',
        help_text='Email the student when a document status is changed.',
    )

    status_change_email_subject = forms.CharField(
        required=False,
        max_length=200,
        label='Status Change Email Subject',
    )

    status_change_email = forms.CharField(
        required=False,
        widget=forms.Textarea,
        label='Status Change Email',
        help_text=('Sent to the student when a document status changes. '
                   'Placeholders: {{student_first_name}}, {{student_last_name}}, '
                   '{{document_type}}, {{status}}.'),
    )

    # Named to avoid confusion with `statuses`, which are *document* statuses.
    document_check_registration_statuses = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
        label='Registration Statuses Requiring Documents',
        help_text=('Supporting-document requirements apply to courses whose '
                   'registration is in one of these statuses.'),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filled here, not at class level, so loading the setting module
        # does not import the models.
        from ..models.section import StudentRegistration
        self.fields['document_check_registration_statuses'].choices = (
            StudentRegistration.STATUS_OPTIONS)

        # Once DocumentType is seeded, the upload dropdown reads it instead
        # (#45), so this list is kept only for reference until release 2
        # (#47) removes it.
        from ..models.course import DocumentType
        if DocumentType.objects.exists():
            self.fields['types'].disabled = True
            self.fields['types'].help_text = (
                'Read-only: document types are now managed on the Document '
                'Types page (Classes > Document Types).')

    def _stored_types(self):
        try:
            value = Setting.objects.get(key=support_docs.key).value or {}
        except Setting.DoesNotExist:
            return []
        return value.get('types', [])

    def _to_python(self):
        return {
            # A disabled field cleans to its `initial`, which the settings
            # app doesn't pass on save -- keep the stored list, not a blank.
            'types': (self._stored_types() if self.fields['types'].disabled
                      else _lines_to_list(self.cleaned_data.get('types'))),
            'statuses': _lines_to_list(self.cleaned_data.get('statuses')),
            'email_enabled': self.cleaned_data.get('email_enabled', 'No'),
            'status_change_email_subject': self.cleaned_data.get('status_change_email_subject', ''),
            'status_change_email': self.cleaned_data.get('status_change_email', ''),
            'document_check_registration_statuses': list(
                self.cleaned_data.get('document_check_registration_statuses') or []),
        }


class support_docs(SettingForm):
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
    def from_db(cls):
        # Populate the form: lists render back into their textareas.
        try:
            v = Setting.objects.get(key=cls.key).value or {}
        except Setting.DoesNotExist:
            return {
                'document_check_registration_statuses':
                    list(DEFAULT_DOCUMENT_CHECK_REGISTRATION_STATUSES),
            }
        return {
            'types': '\n'.join(v.get('types', [])),
            'statuses': '\n'.join(v.get('statuses', [])),
            'email_enabled': v.get('email_enabled', 'No'),
            'status_change_email_subject': v.get('status_change_email_subject', ''),
            'status_change_email': v.get('status_change_email', ''),
            'document_check_registration_statuses': v.get(
                'document_check_registration_statuses',
                list(DEFAULT_DOCUMENT_CHECK_REGISTRATION_STATUSES)),
        }

    @classmethod
    def get_config(cls):
        """The full stored settings dict (empty dict if unset)."""
        try:
            return Setting.objects.get(key=cls.key).value or {}
        except Setting.DoesNotExist:
            return {}

    @classmethod
    def get_types(cls):
        return cls.get_config().get('types', [])

    @classmethod
    def get_statuses(cls):
        return cls.get_config().get('statuses', [])

    @classmethod
    def get_document_check_registration_statuses(cls):
        """Registration statuses whose courses still need supporting documents.

        The saved list when CE has saved one -- even an empty one -- else the
        default.
        """
        config = cls.get_config()
        if 'document_check_registration_statuses' in config:
            return config['document_check_registration_statuses']
        return list(DEFAULT_DOCUMENT_CHECK_REGISTRATION_STATUSES)

    def install(self):
        # Don't clobber an existing value on re-registration.
        if Setting.objects.filter(key=self.key).exists():
            return

        # Migrate values from the now-merged split settings, if present.
        def _old(k):
            try:
                return Setting.objects.get(key=k).value.get('items', [])
            except (Setting.DoesNotExist, AttributeError):
                return []

        setting = Setting(key=self.key)
        setting.value = {
            'types': _old('cis.settings.support_doc_types'),
            'statuses': _old('cis.settings.support_doc_statuses'),
            'email_enabled': 'No',
            'status_change_email_subject': 'Your document status has been updated',
            'status_change_email': (
                'Hi {{student_first_name}},\n\n'
                'The status of your document "{{document_type}}" is now {{status}}.'
            ),
            'document_check_registration_statuses':
                list(DEFAULT_DOCUMENT_CHECK_REGISTRATION_STATUSES),
        }
        setting.save()

        # Remove the superseded split settings + their registry records.
        Setting.objects.filter(key__in=_OLD_KEYS).delete()
        try:
            import importlib.util
            if importlib.util.find_spec('setting.setting'):
                from setting.setting.models.setting import SettingRecord
            else:
                from setting.models.setting import SettingRecord
            SettingRecord.objects.filter(
                name__in=['support_doc_types', 'support_doc_statuses']).delete()
        except Exception:
            pass

    def run_record(self):
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key
        setting.value = self._to_python()
        setting.save()
        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success'})
