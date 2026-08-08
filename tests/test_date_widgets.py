"""Opt-in date widgets (cis.forms.widgets).

These are a library — no existing form references them — so the tests cover the
behaviours a tenant would be opting in to, and the Django/packaging warts each
class exists to absorb.
"""
import datetime
from unittest.mock import patch

from django import forms
from django.test import SimpleTestCase, TestCase

from cis.academic_calendar import graduation_years
from cis.forms.widgets import (
    BlankFirstGraduationWidget,
    BlankFirstSelectDateWidget,
    DatePickerInput,
    birth_date_bounds,
    date_bounds_attrs,
    date_of_birth_widget,
    graduation_widget,
)


class BlankFirstTests(SimpleTestCase):
    """SelectDateWidget hides its empty option on a required field, so the
    control renders pre-set to a value the user never chose."""

    def test_stock_widget_omits_blank_when_required(self):
        # Establishes the wart the mixin exists for; if Django ever fixes this,
        # this test fails and the mixin can go.
        widget = forms.SelectDateWidget()
        widget.is_required = True
        html = widget.render('d', None, attrs={'id': 'id_d'})
        self.assertNotIn('value=""', html)

    def test_blank_first_renders_blank_even_when_required(self):
        widget = BlankFirstSelectDateWidget()
        widget.is_required = True
        html = widget.render('d', None, attrs={'id': 'id_d'})
        self.assertIn('value=""', html)

    def test_is_required_is_restored_afterwards(self):
        widget = BlankFirstSelectDateWidget()
        widget.is_required = True
        widget.render('d', None, attrs={'id': 'id_d'})
        self.assertTrue(widget.is_required)

    def test_is_required_restored_even_if_rendering_raises(self):
        widget = BlankFirstSelectDateWidget()
        widget.is_required = True
        with patch.object(forms.SelectDateWidget, 'get_context',
                          side_effect=ValueError('boom')):
            with self.assertRaises(ValueError):
                widget.render('d', None, attrs={'id': 'id_d'})
        self.assertTrue(widget.is_required)

    def test_graduation_widget_is_blank_first(self):
        widget = BlankFirstGraduationWidget(years=[2027, 2028, 2029, 2030])
        widget.is_required = True
        html = widget.render('g', None, attrs={'id': 'id_g'})
        self.assertIn('value=""', html)


class DatePickerInputTests(SimpleTestCase):
    def test_renders_a_native_date_input(self):
        html = DatePickerInput().render('dob', None, attrs={'id': 'id_dob'})
        self.assertIn('type="date"', html)

    def test_type_is_not_duplicated_when_passed_in_attrs(self):
        """Input.__init__ pops `type` out of attrs onto self.input_type; a
        caller re-adding it would otherwise render the attribute twice."""
        html = DatePickerInput(attrs={'type': 'date'}).render(
            'dob', None, attrs={'id': 'id_dob'})
        self.assertEqual(html.count('type="date"'), 1)

    def test_carries_the_picker_script(self):
        self.assertIn('js/date_picker.js', str(DatePickerInput().media))

    def test_media_merges_into_a_form(self):
        # The reason this is a subclass at all: templates inside the installed
        # cis package cannot add a <script> tag, but they do render form.media.
        class F(forms.Form):
            dob = forms.DateField(widget=DatePickerInput())

        self.assertIn('js/date_picker.js', str(F().media))

    def test_existing_iso_value_prefills(self):
        html = DatePickerInput().render(
            'dob', datetime.date(2009, 3, 4), attrs={'id': 'id_dob'})
        self.assertIn('value="2009-03-04"', html)


class DateBoundsTests(SimpleTestCase):
    def test_absent_bounds_are_omitted_not_blank(self):
        self.assertEqual(date_bounds_attrs(None, None), {})

    def test_bounds_render_as_iso(self):
        attrs = date_bounds_attrs(datetime.date(2006, 1, 2),
                                  datetime.date(2012, 12, 31))
        self.assertEqual(attrs, {'min': '2006-01-02', 'max': '2012-12-31'})

    def test_only_one_bound_is_fine(self):
        self.assertEqual(date_bounds_attrs(max_date=datetime.date(2012, 1, 1)),
                         {'max': '2012-01-01'})


class BirthDateBoundsTests(TestCase):
    """An unreadable setting must loosen the picker, never raise — the window
    is still enforced server-side by Student.is_valid_age_range."""

    def _with_setting(self, value):
        return patch('cis.settings.registrations.registrations.from_db',
                     return_value=value)

    def test_reads_the_window(self):
        with self._with_setting({'starting_birth_date': '01/02/2006',
                                 'ending_birth_date': '12/31/2012'}):
            self.assertEqual(
                birth_date_bounds(),
                (datetime.date(2006, 1, 2), datetime.date(2012, 12, 31)))

    def test_missing_setting_yields_no_bounds(self):
        with self._with_setting({}):
            self.assertEqual(birth_date_bounds(), (None, None))

    def test_unparseable_setting_yields_no_bounds(self):
        with self._with_setting({'starting_birth_date': 'not-a-date',
                                 'ending_birth_date': '12/31/2012'}):
            self.assertEqual(birth_date_bounds(), (None, None))

    def test_inverted_window_yields_no_bounds(self):
        with self._with_setting({'starting_birth_date': '12/31/2012',
                                 'ending_birth_date': '01/02/2006'}):
            self.assertEqual(birth_date_bounds(), (None, None))


class FactoryTests(TestCase):
    def test_graduation_widget_offers_the_derivable_years(self):
        widget = graduation_widget()
        self.assertEqual(list(widget.years), graduation_years())

    def test_presentation_stays_with_the_caller(self):
        # CSS classes are a tenant choice, so nothing is baked in.
        self.assertNotIn('class', graduation_widget().attrs)
        self.assertEqual(
            graduation_widget(css_class='w-auto').attrs['class'], 'w-auto')

    def test_date_of_birth_widget_applies_setting_bounds(self):
        with patch('cis.forms.widgets.birth_date_bounds',
                   return_value=(datetime.date(2006, 1, 2),
                                 datetime.date(2012, 12, 31))):
            widget = date_of_birth_widget(css_class='col-md-6')
        self.assertEqual(widget.attrs['min'], '2006-01-02')
        self.assertEqual(widget.attrs['max'], '2012-12-31')
        self.assertEqual(widget.attrs['class'], 'col-md-6')
        # `type` belongs to input_type, never attrs.
        self.assertNotIn('type', widget.attrs)

    def test_date_of_birth_widget_without_bounds_still_builds(self):
        with patch('cis.forms.widgets.birth_date_bounds',
                   return_value=(None, None)):
            widget = date_of_birth_widget()
        self.assertNotIn('min', widget.attrs)
        self.assertNotIn('max', widget.attrs)


class NoExistingFormChangedTests(SimpleTestCase):
    """This is a library. The spec engine keeps building its own DateInput."""

    def test_spec_engine_still_uses_plain_dateinput(self):
        import inspect
        from cis.forms import application_fields

        source = inspect.getsource(application_fields._date)
        self.assertIn('forms.DateInput', source)
        self.assertNotIn('DatePickerInput', source)
