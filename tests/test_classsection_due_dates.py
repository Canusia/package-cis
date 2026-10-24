"""Optional ClassSection due dates (#86): four nullable fields, on the
section form only when settings.CLASS_SECTION_DUE_DATES is on, and a dates
card on the details tab only when a section has any of them."""
from datetime import date

from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from cis.forms.section import ClassSectionForm
from cis.models.section import ClassSection

FIELDS = ('registration_start_date', 'registration_end_date',
          'payment_due_date', 'grade_due_date')


class ClassSectionDueDateModelTests(SimpleTestCase):
    def test_fields_are_optional(self):
        for name in FIELDS:
            field = ClassSection._meta.get_field(name)
            self.assertTrue(field.null and field.blank, name)

    def test_history_tracks_them(self):
        history = ClassSection.history.model
        for name in FIELDS:
            history._meta.get_field(name)


class ClassSectionDueDateFormTests(SimpleTestCase):
    def test_hidden_by_default(self):
        form = ClassSectionForm()
        for name in FIELDS:
            self.assertNotIn(name, form.fields)

    @override_settings(CLASS_SECTION_DUE_DATES=True)
    def test_shown_when_enabled(self):
        form = ClassSectionForm()
        for name in FIELDS:
            self.assertIn(name, form.fields)
            self.assertFalse(form.fields[name].required)

    @override_settings(CLASS_SECTION_DUE_DATES=True)
    def test_registration_end_before_start_is_rejected(self):
        form = ClassSectionForm()
        form.cleaned_data = {'registration_start_date': date(2026, 9, 1),
                             'registration_end_date': date(2026, 8, 1)}
        form._errors = {}
        form.clean()
        self.assertIn('registration_end_date', form._errors)


class ClassSectionDueDateCardTests(SimpleTestCase):
    def _render(self, **dates):
        record = ClassSection(**dates)
        record.asHTML = ''
        return render_to_string('cis/sections/tabs/_details.html', {'record': record})

    def test_no_card_without_dates(self):
        self.assertNotIn('Registration Window', self._render())

    def test_card_with_a_date(self):
        html = self._render(grade_due_date=date(2027, 1, 15))
        self.assertIn('Grade Due', html)
        self.assertIn('01/15/2027', html)
