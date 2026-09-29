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
