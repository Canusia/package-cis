"""Form for linking a high school to a campus (building code + status)."""
from django import forms

from cis.campus_gate import get_accessible_campuses
from cis.models.course import Campus
from cis.models.highschool import HighSchoolCampus


class HighSchoolCampusForm(forms.ModelForm):
    """Add (no ``instance``) or edit (``instance``) a HighSchoolCampus.

    Campus choices are the campuses ``user`` may process minus those the
    school is already linked to. On edit the campus is fixed.
    """

    class Meta:
        model = HighSchoolCampus
        fields = ['campus', 'building_code', 'status']

    def __init__(self, *args, user=None, highschool=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.highschool = highschool or getattr(self.instance, 'highschool', None)
        if not self.instance._state.adding:
            del self.fields['campus']
        else:
            linked = self.highschool.campus_links.values_list('campus_id', flat=True)
            self.fields['campus'] = forms.ModelChoiceField(
                queryset=get_accessible_campuses(user).exclude(pk__in=list(linked)).order_by('name'),
                empty_label='Select a campus')
        self.fields['building_code'].required = False
        self.fields['building_code'].help_text = (
            'The code this campus\'s SIS uses for the school. Leave blank if none.')

    def clean_building_code(self):
        return (self.cleaned_data.get('building_code') or '').strip()

    def clean(self):
        cleaned = super().clean()
        campus = self.instance.campus if not self.instance._state.adding else cleaned.get('campus')
        code = cleaned.get('building_code')
        if campus and code:
            clash = (HighSchoolCampus.objects
                     .filter(campus=campus, building_code=code)
                     .exclude(pk=self.instance.pk)
                     .select_related('highschool').first())
            if clash:
                self.add_error(
                    'building_code',
                    f'Building code "{code}" is already used by '
                    f'{clash.highschool.name} at {campus.name}.')
        return cleaned

    def save(self, commit=True):
        link = super().save(commit=False)
        if self.instance._state.adding:
            link.highschool = self.highschool
        if commit:
            link.save()
        return link
