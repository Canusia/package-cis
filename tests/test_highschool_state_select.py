"""High School State filtering for the student application (#114 item 11):
HighSchoolStateSelect tags options with data-state, and the helpers build
the picker's choices and initial value."""
import uuid

from django import forms
from django.test import TestCase

from cis.forms.widgets import (
    HighSchoolStateSelect, highschool_state_choices, highschool_state_initial,
)
from cis.models.highschool import HighSchool


class HighSchoolStateSelectTests(TestCase):
    def setUp(self):
        sfx = uuid.uuid4().hex[:6]
        self.idaho = HighSchool.objects.create(name=f'Boise-{sfx}', state='ZI', status='Active')
        self.oregon = HighSchool.objects.create(name=f'Ontario-{sfx}', state='ZO', status='Active')
        HighSchool.objects.create(name=f'Old-{sfx}', state='ZX', status='Inactive')

    def test_options_carry_the_school_state(self):
        class F(forms.Form):
            highschool = forms.ModelChoiceField(
                queryset=HighSchool.objects.filter(pk__in=[self.idaho.pk, self.oregon.pk]),
                widget=HighSchoolStateSelect)
        html = str(F()['highschool'])
        self.assertIn(f'value="{self.idaho.pk}" data-state="ZI"', html)
        self.assertIn('data-state="ZO"', html)

    def test_choices_are_active_states(self):
        values = [v for v, _ in highschool_state_choices()]
        self.assertEqual(values[0], '')
        self.assertIn('ZI', values)
        self.assertNotIn('ZX', values)

    def test_stored_state_stays_selectable(self):
        self.assertIn('ZX', [v for v, _ in highschool_state_choices(include='ZX')])

    def test_initial_prefers_the_current_school(self):
        # A stored state from before the school changed must not hide it.
        student = type('S', (), {'highschool': self.oregon})()
        self.assertEqual(highschool_state_initial(student, stored='ZI'), 'ZO')
        self.assertEqual(highschool_state_initial(student), 'ZO')
        no_school = type('S', (), {'highschool': None})()
        self.assertEqual(highschool_state_initial(no_school, stored='ZI'), 'ZI')
        self.assertEqual(highschool_state_initial(None), '')
