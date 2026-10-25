"""Add / edit a high school's recommender bucket (CE and HS-admin portals)."""
from django import forms
from django.db import transaction
from django.utils.html import escape

from cis.models.highschool_administrator import ANY_CAMPUS
from cis.models.recommender_bucket import LETTER_CHOICES, RecommenderBucket


class PositionChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.hsadmin} — {obj.position.name}'


class RecommenderBucketForm(forms.ModelForm):
    start_letter = forms.ChoiceField(choices=LETTER_CHOICES, label='From')
    end_letter = forms.ChoiceField(choices=LETTER_CHOICES, label='To', initial='Z')
    members = PositionChoiceField(
        queryset=None, required=False, widget=forms.CheckboxSelectMultiple,
        label='Counselors',
        help_text='Only active personnel who can manage student recommendations are listed. '
                  'A counselor in no bucket recommends for every student at the school.')

    class Meta:
        model = RecommenderBucket
        fields = ['name', 'start_letter', 'end_letter']
        help_texts = {'name': 'For example "A–F" or "Ms. Lee\'s students".'}

    def __init__(self, *args, highschool, **kwargs):
        super().__init__(*args, **kwargs)
        from cis.services.recommender_scope import recommender_positions
        self.highschool = highschool
        self.fields['members'].queryset = recommender_positions(
            ANY_CAMPUS, highschool_ids=[highschool.id]).select_related(
            'hsadmin__user', 'position').order_by('hsadmin__user__last_name')
        if self.instance.pk:
            self.fields['members'].initial = list(
                self.instance.positions.values_list('pk', flat=True))

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        clash = RecommenderBucket.objects.filter(
            highschool=self.highschool, name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError('This school already has a bucket with that name.')
        return name

    def clean(self):
        data = super().clean()
        start, end = data.get('start_letter'), data.get('end_letter')
        if start and end and start > end:
            self.add_error('end_letter', '"To" must not come before "From".')
        return data

    def save(self, user):
        from cis.models.note import HighSchoolNote
        from cis.services.recommender_scope import set_bucket_members

        creating = self.instance.pk is None
        with transaction.atomic():
            bucket = super().save(commit=False)
            bucket.highschool = self.highschool
            bucket.save()
            members = list(self.cleaned_data['members'])
            set_bucket_members(bucket, members)
            # Notes render as HTML on the CE Notes tab, and HS admins choose
            # the bucket name: escape it.
            names = ', '.join(escape(str(p.hsadmin)) for p in members) or 'nobody'
            HighSchoolNote.objects.create(
                highschool=self.highschool, createdby=user,
                note=f'{"Added" if creating else "Updated"} recommender bucket '
                     f'{escape(bucket.name)} ({bucket.range_label}): {names}.')
        return bucket
