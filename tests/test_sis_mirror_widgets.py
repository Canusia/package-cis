"""The SIS mirror setting's term and stop-on-error lists are scrollable
multi-selects (like class_section_importer), not long checkbox lists."""
import json

from django.forms import CheckboxSelectMultiple, SelectMultiple
from django.test import RequestFactory, TestCase

from cis.models.settings import Setting
from cis.models.term import AcademicYear, Term
from cis.settings.registration_status_email import (
    record_sis_mirror_errors, registration_status_email, sis_error_key)

FIELDS = ('sis_mirror_terms', 'sis_mirror_stop_on_errors')


class SisMirrorWidgetTests(TestCase):
    def setUp(self):
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': ['registered']}})
        record_sis_mirror_errors('registration', ['Holds prevent registration.'])
        ay = AcademicYear.objects.create(name='2026-2027')
        self.term = Term.objects.create(label='Fall 2026', code='26FA', academic_year=ay)
        self.form = registration_status_email(RequestFactory().get('/'))

    def test_both_lists_are_scrollable_multi_selects(self):
        for name in FIELDS:
            widget = self.form.fields[name].widget
            self.assertIs(type(widget), SelectMultiple, name)
            self.assertNotIsInstance(widget, CheckboxSelectMultiple)
            self.assertEqual(widget.attrs.get('size'), 10, name)
            self.assertEqual(widget.attrs.get('class'), 'col-md-8 col-sm-12', name)
            self.assertFalse(self.form.fields[name].required)

    def test_help_text_explains_multi_select(self):
        for name in FIELDS:
            self.assertIn('Ctrl-click (Cmd-click on a Mac)', self.form.fields[name].help_text)
            self.assertNotIn('Tick', self.form.fields[name].help_text)

    def test_saved_selection_still_validates_and_round_trips(self):
        key = sis_error_key('Holds prevent registration.')
        terms = self.form.fields['sis_mirror_terms'].clean([str(self.term.id)])
        errors = self.form.fields['sis_mirror_stop_on_errors'].clean([key])
        self.assertEqual(terms, [str(self.term.id)])
        self.assertEqual(errors, [key])
        json.dumps([terms, errors])
        html = str(self.form['sis_mirror_terms'])
        self.assertIn('<select', html)
        self.assertIn('multiple', html)
        self.assertIn('size="10"', html)
