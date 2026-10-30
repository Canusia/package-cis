"""Term.by_code (#94): Term.code is not unique, so code lookups in importers
and the class-section API are limited to the active campus (plus campus-less
years) in multi-campus mode. Single-campus lookups are unchanged."""
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.term import AcademicYear, Term


def _sfx():
    return uuid.uuid4().hex[:8]


class TermByCodeTests(TestCase):
    def setUp(self):
        prefix = settings.CAMPUS_CODE_PREFIX
        self.campus_a = Campus.objects.create(name=f'A-{_sfx()}', code=f'{prefix}-{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B-{_sfx()}', code=f'{prefix}-{_sfx()}')
        self.code = _sfx()[:6]
        self.term_a = Term.objects.create(
            academic_year=AcademicYear.objects.create(name=f'A{_sfx()}', campus=self.campus_a),
            code=self.code, label='Fall')
        self.term_b = Term.objects.create(
            academic_year=AcademicYear.objects.create(name=f'B{_sfx()}', campus=self.campus_b),
            code=self.code, label='Fall')

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_lookup_uses_the_active_campus(self):
        with campus_context(self.campus_b):
            self.assertEqual(list(Term.by_code(self.code)), [self.term_b])
        with campus_context(self.campus_a):
            self.assertEqual(Term.by_code(self.code).get(), self.term_a)

    @override_settings(MULTI_CAMPUS=True)
    def test_explicit_campus_wins(self):
        self.assertEqual(list(Term.by_code(self.code, campus=self.campus_b)), [self.term_b])

    @override_settings(MULTI_CAMPUS=True)
    def test_campus_less_year_is_a_fallback(self):
        with override_settings(MULTI_CAMPUS=False):  # legacy campus-less year
            shared = Term.objects.create(
                academic_year=AcademicYear.objects.create(name=f'N{_sfx()}'),
                code=self.code, label='Spring')
        self.assertEqual(list(Term.by_code(self.code, campus=self.campus_a)),
                         [self.term_a, shared])

    @override_settings(MULTI_CAMPUS=False)
    def test_single_campus_lookup_is_unchanged(self):
        self.assertEqual(set(Term.by_code(self.code)), {self.term_a, self.term_b})

    @override_settings(MULTI_CAMPUS=True)
    def test_class_section_importer_picks_the_campus_term(self):
        from cis.services.importers.class_section_importer import ClassSectionImporter
        importer = ClassSectionImporter()
        with campus_context(self.campus_b):
            self.assertEqual(importer._get_term(self.code), self.term_b)

    @override_settings(MULTI_CAMPUS=True)
    def test_api_term_lookup_prefers_the_campus_term(self):
        from cis.api.class_section import _term_by_code
        with override_settings(MULTI_CAMPUS=False):  # legacy campus-less year
            Term.objects.create(
                academic_year=AcademicYear.objects.create(name=f'N{_sfx()}'),
                code=self.code, label='Spring')
        with campus_context(self.campus_a):
            self.assertEqual(_term_by_code(self.code), self.term_a)

    @override_settings(MULTI_CAMPUS=False)
    def test_api_term_lookup_single_campus_still_rejects_duplicates(self):
        from cis.api.class_section import _term_by_code
        with self.assertRaises(Term.MultipleObjectsReturned):
            _term_by_code(self.code)
        with self.assertRaises(Term.DoesNotExist):
            _term_by_code('nope' + _sfx())
