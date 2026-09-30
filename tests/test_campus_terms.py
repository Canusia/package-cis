"""MC-07 (#31): active_term(campus) / registration_terms(campus).

Both take an optional campus (default: current_campus()). In multi-campus
mode they read that campus's own cis_registrations setting (MC-05), raise
TermNotConfigured instead of falling back to Term.objects.first(), and refuse
a configured term that belongs to another campus. Single-campus mode keeps
today's first-term fallback.
"""
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.settings import Setting
from cis.models.term import AcademicYear, Term
from cis.utils import TermNotConfigured, active_term, registration_terms

KEY = f'{settings.CAMPUS_CODE_PREFIX}_cis_registrations'


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


def _term(campus, code):
    year = AcademicYear.objects.create(name=f'AY-{uuid.uuid4().hex[:6]}', campus=campus)
    return Term.objects.create(academic_year=year, code=code, label=code)


class SingleCampusFallbackTests(TestCase):
    def test_falls_back_to_the_first_term_when_unset(self):
        Setting.objects.filter(key=KEY).delete()
        first = _term(None, 'F1')
        self.assertEqual(active_term(), Term.objects.first())
        self.assertIsNotNone(first)


@override_settings(MULTI_CAMPUS=True)
class MultiCampusTermTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')
        self.t1 = _term(self.c1, 'C1-FA')
        self.t2 = _term(self.c2, 'C2-FA')
        Setting.objects.create(key=KEY, campus=self.c1, value={
            'active_term': str(self.t1.id), 'registration_terms': [str(self.t1.id)]})
        Setting.objects.create(key=KEY, campus=self.c2, value={
            'active_term': str(self.t2.id), 'registration_terms': [str(self.t2.id)]})

    def test_each_campus_gets_its_own_term(self):
        self.assertEqual(active_term(self.c1), self.t1)
        self.assertEqual(active_term(self.c2), self.t2)
        with campus_context(self.c2):
            self.assertEqual(active_term(), self.t2)
            self.assertEqual(list(registration_terms()), [self.t2])
        self.assertEqual(list(registration_terms(self.c1)), [self.t1])

    def test_unset_raises_instead_of_first_term(self):
        c3 = _campus('C3')
        with self.assertRaises(TermNotConfigured):
            active_term(c3)

    def test_term_from_another_campus_is_refused(self):
        Setting.objects.filter(key=KEY, campus=self.c1).update(value={
            'active_term': str(self.t2.id), 'registration_terms': [str(self.t2.id)]})
        with self.assertRaises(TermNotConfigured):
            active_term(self.c1)
        with self.assertRaises(TermNotConfigured):
            registration_terms(self.c1)


class BlankActiveTermTests(TestCase):
    """A registrations setting saved with an empty active_term is 'not set',
    not a 500 from Term.objects.get(pk='')."""

    @override_settings(MULTI_CAMPUS=False)
    def test_single_campus_blank_falls_back_to_the_first_term(self):
        Setting.objects.filter(key=KEY).delete()
        _term(None, 'F1')
        Setting.objects.create(key=KEY, value={'active_term': ''})
        self.assertEqual(active_term(), Term.objects.first())

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_blank_raises_term_not_configured(self):
        c1 = _campus('C1')
        Setting.objects.create(key=KEY, campus=c1, value={'active_term': ''})
        with self.assertRaises(TermNotConfigured):
            active_term(c1)


@override_settings(MULTI_CAMPUS=True)
class RegistrationFormCampusChoicesTests(TestCase):
    """The registrations setting form offers only the current campus's terms
    and academic years, so a campus cannot save another campus's term."""

    def test_choices_are_the_current_campus_only(self):
        from cis.settings.registrations import RegistrationForm
        c1, c2 = _campus('C1'), _campus('C2')
        t1, t2 = _term(c1, 'C1-FA'), _term(c2, 'C2-FA')
        with campus_context(c2):
            form = RegistrationForm()
        for field in ('active_term', 'registration_terms'):
            ids = {value for value, _ in form.fields[field].choices}
            self.assertIn(str(t2.id), ids)
            self.assertNotIn(str(t1.id), ids)
        years = {value for value, _ in form.fields['academic_year'].choices}
        self.assertEqual(years, {str(t2.academic_year_id)})


@override_settings(MULTI_CAMPUS=True)
class CampusDetailTermTests(TestCase):
    """The campus detail page shows the viewed campus's terms, whichever
    campus's host it is opened from."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.c1, self.c2 = _campus('C1'), _campus('C2')
        self.t1, self.t2 = _term(self.c1, 'C1-FA'), _term(self.c2, 'C2-FA')
        Setting.objects.create(key=KEY, campus=self.c1, value={'active_term': str(self.t1.id)})
        self.user = get_user_model().objects.create(
            username=f'ce-{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@example.com')

    def _context(self, record, host_campus):
        from unittest import mock
        from django.http import HttpResponse
        from django.test import RequestFactory
        from cis.views import campus as campus_views
        request = RequestFactory().get('/')
        request.user = self.user
        with mock.patch.object(campus_views, 'render', return_value=HttpResponse()) as render, \
                mock.patch.object(campus_views, 'draw_menu', return_value=''), \
                campus_context(host_campus):
            campus_views.detail(request, record.id)
        return render.call_args.args[2]

    def test_viewing_another_campus_uses_that_campus_terms(self):
        context = self._context(self.c1, host_campus=self.c2)
        self.assertEqual(context['active_term'], self.t1)
        self.assertEqual(list(context['terms']), [self.t1])

    def test_campus_without_an_active_term_renders(self):
        context = self._context(self.c2, host_campus=self.c1)
        self.assertIsNone(context['active_term'])
        self.assertEqual(list(context['terms']), [self.t2])
