"""Opt-in date controls shared by tenant forms.

Nothing here is wired into an existing form. These are a library: a tenant that
wants a real date picker, or selects that start blank, imports one. Existing
forms — including the spec-driven application path, which builds its own
``forms.DateInput`` in ``cis/forms/application_fields.py::_date`` — are
unchanged.

The two controls are deliberately different shapes because they capture
different facts. A birth date is a date, so it gets a native
``<input type="date">``. A graduation date is a month/year fact whose day is
meaningless (always stored as the 1st), and the native ``<input type="month">``
is unsupported in Firefox and desktop Safari, where it degrades silently to a
bare text box — so that one stays a pair of selects.

Presentation stays with the caller. CSS classes are constructor arguments, not
constants here, because column widths are a tenant styling choice.
"""
import datetime
import logging

from django import forms

from form_fields import fields as FFields

logger = logging.getLogger(__name__)

ISO = '%Y-%m-%d'

#: The birth-date window on the registrations setting is authored in the admin
#: UI's display format, not ISO.
SETTING_FORMAT = '%m/%d/%Y'

#: Django's ``SelectDateWidget`` takes empty labels in (year, month, day)
#: order — see its ``__init__``, which unpacks the tuple in exactly that
#: sequence. The graduation widget renders month then year and never renders
#: the day, so the third entry exists only to satisfy the 3-element
#: requirement.
GRADUATION_EMPTY_LABELS = ('Year', 'Month', 'Day')


class BlankFirstMixin:
    """Render the empty choice even when the bound field is required.

    ``SelectDateWidget`` offers its ``('', '---')`` option only when the field
    is not required::

        if not self.is_required:
            choices.insert(0, self.none_value)

    A required date-select therefore renders pre-set to its first entry —
    January of the earliest offered year, which on a graduation field is
    already in the past. An untouched control submits a date the student never
    chose and then fails validation on it.

    Flipping ``is_required`` for the duration of ``get_context`` renders the
    blank option while leaving the *field* required, so an untouched control
    submits nothing and Django reports "This field is required" against it —
    the honest outcome.
    """

    def get_context(self, name, value, attrs):
        was_required = self.is_required
        self.is_required = False
        try:
            return super().get_context(name, value, attrs)
        finally:
            self.is_required = was_required


class BlankFirstSelectDateWidget(BlankFirstMixin, forms.SelectDateWidget):
    """Day/Month/Year selects that start blank."""


class BlankFirstGraduationWidget(BlankFirstMixin,
                                 FFields.GraduationMonthYearWidget):
    """Month/Year selects that start blank.

    Pass ``years=graduation_years()`` (from ``cis.academic_calendar``) so the
    offered range comes from the same place the grade level is derived.
    """


class DatePickerInput(forms.DateInput):
    """``<input type="date">`` whose picker opens from anywhere in the field.

    ``input_type`` is a class attribute rather than something passed in
    ``attrs``. ``Input.__init__`` pops ``type`` out of ``attrs`` onto
    ``self.input_type``::

        self.input_type = attrs.pop("type", self.input_type)

    so ``DateInput(attrs={'type': 'date'})`` renders correctly but leaves
    ``attrs`` empty — and anything that later does ``attrs.update(...)`` with a
    ``type`` renders the attribute twice. Setting it here means no caller can
    reintroduce that.

    The ``Media`` is the reason this is a subclass at all: ``date_picker.js``
    has to reach templates inside the installed cis package, where a
    ``<script>`` tag cannot be added. Widget media merges into ``form.media``,
    which those templates already render.
    """

    input_type = 'date'

    class Media:
        js = ('js/date_picker.js',)

    def __init__(self, attrs=None, format=None):
        # A date input only round-trips ISO. Django's default
        # DATE_INPUT_FORMATS already starts with ISO for en-us, but pinning it
        # keeps an existing value prefilling if the active locale ever changes.
        super().__init__(attrs=attrs, format=format or ISO)


def date_bounds_attrs(min_date=None, max_date=None):
    """``min`` / ``max`` for a date input, omitting absent bounds.

    Deliberately carries no ``'type': 'date'`` — see ``DatePickerInput``.
    An absent bound is omitted rather than sent empty, because ``min=""`` is
    not the same as no ``min`` to a browser.
    """
    attrs = {}
    if min_date:
        attrs['min'] = min_date.strftime(ISO)
    if max_date:
        attrs['max'] = max_date.strftime(ISO)
    return attrs


def birth_date_bounds():
    """The registrations setting's birth-date window as ``(start, end)``.

    ``(None, None)`` when the setting is missing or unparseable. The window is
    still enforced server-side by ``Student.is_valid_age_range``, so an absent
    bound loosens the picker, never the rule.
    """
    from cis.settings.registrations import registrations as regis_settings

    try:
        config = regis_settings.from_db()
        start = datetime.datetime.strptime(
            config.get('starting_birth_date'), SETTING_FORMAT).date()
        end = datetime.datetime.strptime(
            config.get('ending_birth_date'), SETTING_FORMAT).date()
        if start < end:
            return start, end
    except (ValueError, TypeError, KeyError) as e:
        logger.warning('Could not read birth-date window: %s', e)
    return None, None


def date_of_birth_widget(css_class=None):
    """A birth-date picker bounded by the registrations setting."""
    attrs = dict(date_bounds_attrs(*birth_date_bounds()))
    if css_class:
        attrs['class'] = css_class
    return DatePickerInput(attrs=attrs)


def graduation_widget(css_class=None, empty_label=GRADUATION_EMPTY_LABELS):
    """Blank-first Month/Year selects over the derivable graduation years."""
    from cis.academic_calendar import graduation_years

    attrs = {'class': css_class} if css_class else {}
    return BlankFirstGraduationWidget(
        attrs=attrs,
        empty_label=empty_label,
        years=graduation_years(),
    )
