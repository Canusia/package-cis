"""Stand-in tenant recommendation form.

Its vocabulary is deliberately nobody's: no tenant declares
`counselor_marker` or `local_assessment`, so a test asserting on them cannot
accidentally pass because it happens to match the tenant this package was
extracted from.
"""
from django import forms


class StudentRecommendationForm(forms.Form):
    # Structural fields every rec form carries; not part of the counselor's
    # answer set and not expected in an export.
    student = forms.CharField(required=True, widget=forms.HiddenInput())
    term = forms.CharField(required=False, widget=forms.HiddenInput())
    student_state_id = forms.CharField(required=False, widget=forms.HiddenInput())
    upload_label = forms.CharField(required=False)
    upload = forms.FileField(required=False)

    # The tenant's actual questions.
    student_gpa = forms.CharField(required=False, label="Student's GPA")
    counselor_marker = forms.ChoiceField(
        required=False,
        label='Counselor Marker',
        choices=[('', 'Select'), ('yes', 'Yes'), ('no', 'No')],
    )
    local_assessment = forms.CharField(
        required=False, label='Local Assessment Result')


def as_html(record, html_type='div'):
    return f'<{html_type}></{html_type}>'
