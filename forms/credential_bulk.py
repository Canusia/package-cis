from django import forms

from cis.models.teacher import TeacherCourseCertificate


class CredentialBulkUpdateForm(forms.Form):
    """Bulk-update date fields and/or status on selected certificates.

    Blank fields are left untouched; only provided fields are applied.
    """
    ids = forms.CharField(widget=forms.HiddenInput)
    action = forms.CharField(widget=forms.HiddenInput, initial='bulk_update')

    status = forms.ChoiceField(
        choices=[('', 'Leave unchanged')] + TeacherCourseCertificate.STATUS_OPTIONS,
        required=False, label='Set Status')
    expires_on = forms.DateField(required=False, label='Set Expires On')
    renewal_required_by = forms.DateField(required=False, label='Set Renewal Required By')
    last_renewed_on = forms.DateField(required=False, label='Set Last Renewed On')

    def __init__(self, ids='', *args, **kwargs):
        super().__init__(*args, **kwargs)
        if ids:
            self.fields['ids'].initial = ids

    def apply(self):
        data = self.cleaned_data
        id_list = [i for i in str(data.get('ids', '')).split(',') if i]
        qs = TeacherCourseCertificate.objects.filter(id__in=id_list)

        updates = {}
        if data.get('status'):
            updates['status'] = data['status']
        if data.get('expires_on'):
            updates['expires_on'] = data['expires_on']
        if data.get('renewal_required_by'):
            updates['renewal_required_by'] = data['renewal_required_by']
        if data.get('last_renewed_on'):
            updates['last_renewed_on'] = data['last_renewed_on']

        if updates:
            return qs.update(**updates)
        return 0
