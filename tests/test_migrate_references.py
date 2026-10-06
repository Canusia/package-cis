"""Migrate tabs move the matched field of real forward references (issue #70).

The old scan offered every relation whose related_model was the record's
class -- reverse relations (a term's own AcademicYear, its parent Term),
simple_history audit tables, and FKs under any name -- and save() then set
one fixed attribute (`obj.term = destination`) on whatever matched. So
ClassSection rows found through registration_term had their *term* moved,
and AcademicYear / Event.term_tbd "moves" were no-ops reported as success.
"""
from django.test import TestCase
from simple_history.models import HistoricalChanges

from cis.forms.course import MigrateCohortForm
from cis.forms.term import MigrateAcademicYearForm, MigrateTermForm
from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term
from cis.utils import (
    get_movable_reference_choices,
    get_movable_reference_fields,
    move_references,
)


def _keys(choices):
    return [key for key, _label in choices]


class MigrateReferencesTestBase(TestCase):
    def setUp(self):
        self.ay = AcademicYear.objects.create(name='2025-2026')
        self.term = Term.objects.create(label='Fall', code='F25', academic_year=self.ay)
        self.dest = Term.objects.create(label='Spring', code='S26', academic_year=self.ay)
        self.other = Term.objects.create(label='Summer', code='U26', academic_year=self.ay)
        self.cohort = Cohort.objects.create(name='Astronomy', designator='A')
        self.course = Course.objects.create(
            catalog_number='001', title='Astronomy', name='A 001', cohort=self.cohort)
        self._n = 0

    def _section(self, term, registration_term):
        # registration_term is explicit: a pre_save signal fills a missing one
        # from term, which would make every section match both FKs.
        self._n += 1
        return ClassSection.objects.create(
            course=self.course, term=term, registration_term=registration_term,
            class_number=str(70000 + self._n), section_number=f'{self._n:03d}')

    def _refresh(self, *objs):
        for obj in objs:
            obj.refresh_from_db()


class MovableReferenceChoicesTests(MigrateReferencesTestBase):
    def test_term_choices_exclude_its_academic_year_and_parent(self):
        self._section(self.term, registration_term=self.other)
        keys = _keys(get_movable_reference_choices(self.term))
        self.assertNotIn('AcademicYear', keys)
        self.assertNotIn('Term', keys)
        self.assertIn('ClassSection.term', keys)
        # No section uses this term as its registration term.
        self.assertNotIn('ClassSection.registration_term', keys)

    def test_reverse_relations_are_never_candidates(self):
        pairs = get_movable_reference_fields(self.term)
        self.assertNotIn((AcademicYear, 'term'), pairs)
        self.assertNotIn((Term, 'sub_terms'), pairs)
        for model_class, field_name in pairs:
            field = model_class._meta.get_field(field_name)
            self.assertTrue(field.concrete and (field.many_to_one or field.one_to_one),
                            f'{model_class.__name__}.{field_name}')

    def test_history_models_never_offered(self):
        section = self._section(self.term, registration_term=self.term)
        section.section_number = '999'
        section.save()  # history rows reference the term through both FKs
        self.assertTrue(ClassSection.history.filter(term=self.term).exists())

        for record in (self.term, self.course, self.cohort):
            for model_class, _f in get_movable_reference_fields(record):
                self.assertFalse(issubclass(model_class, HistoricalChanges), model_class)
            for key in _keys(get_movable_reference_choices(record)):
                self.assertNotIn('Historical', key)

    def test_section_term_and_registration_term_are_separate_choices(self):
        self._section(self.term, registration_term=self.other)
        self._section(self.other, registration_term=self.term)
        choices = dict(get_movable_reference_choices(self.term))
        self.assertEqual(choices['ClassSection.term'], 'ClassSection (term)')
        self.assertEqual(choices['ClassSection.registration_term'],
                         'ClassSection (registration_term)')
        self.assertNotIn('ClassSection', choices)

    def test_single_field_model_keeps_its_bare_name(self):
        # Course has one FK to Cohort (its history table is skipped), so the
        # key stays the bare model name the old form used.
        choices = dict(get_movable_reference_choices(self.cohort))
        self.assertEqual(choices['Course'], 'Course')

    def test_single_field_not_named_after_the_record_shows_the_field(self):
        Term.objects.create(label='Fall A', code='F25A', academic_year=self.ay, parent=self.term)
        self.assertEqual(dict(get_movable_reference_choices(self.term))['Term'], 'Term (parent)')
        self.assertEqual(dict(get_movable_reference_choices(self.ay))['Term'], 'Term')

    def test_academic_year_offers_its_terms(self):
        keys = _keys(get_movable_reference_choices(self.ay))
        self.assertIn('Term', keys)
        self.assertNotIn('Campus', keys)


class MoveReferencesTests(MigrateReferencesTestBase):
    def test_registration_term_move_leaves_term_alone(self):
        a = self._section(self.term, registration_term=self.other)
        b = self._section(self.other, registration_term=self.term)

        success, _msg = move_references(
            self.term, self.dest, ['ClassSection.registration_term'])

        self.assertTrue(success)
        self._refresh(a, b)
        self.assertEqual(b.registration_term, self.dest)
        self.assertEqual(b.term, self.other)
        self.assertEqual((a.term, a.registration_term), (self.term, self.other))

    def test_term_move_leaves_registration_term_alone(self):
        c = self._section(self.term, registration_term=self.term)
        move_references(self.term, self.dest, ['ClassSection.term'])
        self._refresh(c)
        self.assertEqual(c.term, self.dest)
        self.assertEqual(c.registration_term, self.term)

    def test_row_matched_by_two_fields_is_saved_once(self):
        c = self._section(self.term, registration_term=self.term)
        d = self._section(self.term, registration_term=self.other)
        before = ClassSection.history.filter(id__in=[c.id, d.id]).count()

        success, msg = move_references(
            self.term, self.dest, ['ClassSection.term', 'ClassSection.registration_term'])

        self.assertTrue(success, msg)
        self._refresh(c, d)
        self.assertEqual((c.term, c.registration_term), (self.dest, self.dest))
        # d matched only through term: its other registration term is kept.
        self.assertEqual((d.term, d.registration_term), (self.dest, self.other))
        self.assertEqual(ClassSection.history.filter(id__in=[c.id, d.id]).count(), before + 2)
        self.assertEqual(len(msg), 2)
        self.assertTrue(any('ClassSection (term, registration_term)' in m for m in msg), msg)

    def test_unchosen_keys_move_nothing(self):
        a = self._section(self.term, registration_term=self.term)
        success, msg = move_references(self.term, self.dest, [])
        self._refresh(a)
        self.assertEqual((success, msg, a.term), (True, [], self.term))

    def test_sub_term_is_reparented_but_never_onto_itself(self):
        sub = Term.objects.create(
            label='Fall A', code='F25A', academic_year=self.ay, parent=self.term)
        self.assertIn('Term', _keys(get_movable_reference_choices(self.term)))

        success, msg = move_references(self.term, sub, ['Term'])
        self.assertFalse(success)
        self.assertIn('Skipped', msg[0])
        self._refresh(sub)
        self.assertEqual(sub.parent, self.term)

        move_references(self.term, self.dest, ['Term'])
        self._refresh(sub)
        self.assertEqual(sub.parent, self.dest)


class MigrateFormSaveTests(MigrateReferencesTestBase):
    def _data(self, dest, items, action):
        return {'action': action, 'destination_record': str(dest.pk),
                'move_items': items, 'confirm': 'on'}

    def test_term_form_moves_the_chosen_field(self):
        b = self._section(self.other, registration_term=self.term)
        form = MigrateTermForm(record=self.term, data=self._data(
            self.dest, ['ClassSection.registration_term'], 'migrate_term'))
        self.assertTrue(form.is_valid(), form.errors)
        success, _msg = form.save(None, self.term)
        self.assertTrue(success)
        self._refresh(b)
        self.assertEqual((b.term, b.registration_term), (self.other, self.dest))

    def test_term_form_rejects_ambiguous_bare_model_name(self):
        self._section(self.term, registration_term=self.term)
        form = MigrateTermForm(record=self.term, data=self._data(
            self.dest, ['ClassSection'], 'migrate_term'))
        self.assertFalse(form.is_valid())
        self.assertIn('move_items', form.errors)

    def test_academic_year_form_moves_terms(self):
        other_ay = AcademicYear.objects.create(name='2026-2027')
        form = MigrateAcademicYearForm(record=self.ay, data=self._data(
            other_ay, ['Term'], 'migrate_academic_year'))
        self.assertTrue(form.is_valid(), form.errors)
        success, msg = form.save(None, self.ay)
        self.assertTrue(success, msg)
        self.assertEqual(Term.objects.filter(academic_year=other_ay).count(), 3)

    def test_cohort_form_bare_name_still_works(self):
        dest = Cohort.objects.create(name='Biology', designator='B')
        form = MigrateCohortForm(record=self.cohort, data=self._data(
            dest, ['Course'], 'migrate_cohort'))
        self.assertTrue(form.is_valid(), form.errors)
        success, msg = form.save(None, self.cohort)
        self.assertTrue(success, msg)
        self._refresh(self.course)
        self.assertEqual(self.course.cohort, dest)
