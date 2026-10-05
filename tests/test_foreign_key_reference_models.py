"""Migrate-tab choices must not load every referencing row.

The "Select Items to Move" choices only need the names of models that
reference the record. get_foreign_key_references loads every referencing row
(all of a term's sections and their history), which timed out large term,
course and high school detail pages. get_foreign_key_reference_models answers
with one EXISTS per relation instead.
"""
from unittest import mock

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from cis.forms.term import MigrateTermForm
from cis.models import CustomUser
from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term
from cis.utils import get_foreign_key_reference_models, get_foreign_key_references


def _ordered_names(references):
    names = []
    for model_name, _obj in references:
        if model_name not in names:
            names.append(model_name)
    return names


class ForeignKeyReferenceModelsTests(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(name='2025-2026')
        self.term = Term.objects.create(label='Fall', code='F25', academic_year=self.ay)
        self.course = Course.objects.create(
            catalog_number='001', title='Astronomy', name='A 001',
            cohort=Cohort.objects.create(name='Astronomy', designator='A'))

    def _add_sections(self, count, start=0):
        for n in range(start, start + count):
            ClassSection.objects.create(
                course=self.course, term=self.term,
                class_number=90000 + n, section_number=f'{n:03d}')

    def test_matches_the_full_scan(self):
        self._add_sections(3)
        self.assertEqual(
            get_foreign_key_reference_models(self.term),
            _ordered_names(get_foreign_key_references(self.term)))

    def test_matches_the_full_scan_with_no_references(self):
        lonely = Term.objects.create(label='Lonely', code='L1', academic_year=self.ay)
        self.assertEqual(
            get_foreign_key_reference_models(lonely),
            _ordered_names(get_foreign_key_references(lonely)))

    def test_query_count_does_not_grow_with_referencing_rows(self):
        self._add_sections(1)
        with CaptureQueriesContext(connection) as few:
            get_foreign_key_reference_models(self.term)
        self._add_sections(20, start=1)
        with CaptureQueriesContext(connection) as many:
            get_foreign_key_reference_models(self.term)
        self.assertEqual(len(few.captured_queries), len(many.captured_queries))

    def test_loads_no_rows(self):
        self._add_sections(5)
        with mock.patch.object(
                ClassSection, '__init__', side_effect=AssertionError('row loaded')):
            get_foreign_key_reference_models(self.term)

    def test_migrate_term_form_choices_avoid_the_full_scan(self):
        self._add_sections(2)
        expected = _ordered_names(get_foreign_key_references(self.term))
        with mock.patch('cis.forms.term.get_foreign_key_references',
                        side_effect=AssertionError('full scan on GET')):
            form = MigrateTermForm(record=self.term)
        self.assertEqual([v for v, _l in form.fields['move_items'].choices], expected)


class TermDetailMigrateScanTests(TestCase):
    def setUp(self):
        self._saved = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        self.addCleanup(setattr, user_logged_in, 'receivers', self._saved)
        Group.objects.get_or_create(name='ce')
        user = CustomUser.objects.create_superuser(
            username='termce', email='termce@example.com', password='x')
        user.groups.add(Group.objects.get(name='ce'))
        self.client.force_login(user)
        self.term = Term.objects.create(
            label='Fall', code='F25',
            academic_year=AcademicYear.objects.create(name='2025-2026'))

    def test_term_detail_get_never_runs_the_full_scan(self):
        with mock.patch('cis.forms.term.get_foreign_key_references',
                        side_effect=AssertionError('full scan on GET')):
            resp = self.client.get(reverse('cis:term', args=[self.term.id]))
        self.assertEqual(resp.status_code, 200)

    def test_destination_terms_load_academic_year_in_one_query(self):
        for n in range(5):
            Term.objects.create(label=f'T{n}', code=f'C{n}',
                                academic_year=AcademicYear.objects.create(name=f'AY{n}'))
        form = MigrateTermForm(record=self.term)
        with CaptureQueriesContext(connection) as ctx:
            [str(t) for t in form.fields['destination_record'].queryset]
        self.assertEqual(len(ctx.captured_queries), 1)
