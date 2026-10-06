"""cis.services.term_hierarchy: parent/sub-term pickers and filters."""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term
from cis.services.term_hierarchy import (
    filter_by_term, term_tree, term_tree_choices, term_with_descendant_ids,
)


class TermHierarchyTests(TestCase):
    def setUp(self):
        ay = AcademicYear.objects.create(name='2026-2027')

        def term(code, label, parent=None):
            return Term.objects.create(
                academic_year=ay, code=code, label=label, parent=parent)

        self.quarter = term('300', 'Fall Quarter')
        self.semester = term('290', 'Fall Semester', self.quarter)
        self.trimester = term('280', 'Fall Trimester', self.quarter)
        self.block = term('270', 'Block A', self.semester)
        self.spring = term('200', 'Spring')
        self.ordered = Term.objects.filter(academic_year=ay).order_by('-code')

    def test_tree_order_and_depth(self):
        self.assertEqual(
            [(t.label, depth) for t, depth in term_tree(self.ordered)],
            [('Fall Quarter', 0), ('Fall Semester', 1), ('Block A', 2),
             ('Fall Trimester', 1), ('Spring', 0)])

    def test_parent_outside_the_list_is_top_level(self):
        terms = self.ordered.exclude(pk=self.quarter.pk)
        self.assertEqual(
            [(t.label, depth) for t, depth in term_tree(terms)],
            [('Fall Semester', 0), ('Block A', 1), ('Fall Trimester', 0), ('Spring', 0)])

    def test_cycle_does_not_loop_or_drop_terms(self):
        Term.objects.filter(pk=self.quarter.pk).update(parent=self.block)
        tree = term_tree(self.ordered)
        self.assertEqual(sorted(t.label for t, _ in tree), sorted(t.label for t in self.ordered))
        ids = term_with_descendant_ids(self.quarter.pk)
        self.assertEqual(ids, {self.quarter.pk, self.semester.pk, self.trimester.pk, self.block.pk})

    def test_choices_indent_sub_terms(self):
        choices = term_tree_choices(self.ordered, label=lambda t: t.label, indent='-')
        self.assertEqual(choices[:3], [
            (str(self.quarter.pk), 'Fall Quarter'),
            (str(self.semester.pk), '-Fall Semester'),
            (str(self.block.pk), '--Block A'),
        ])

    def test_descendants(self):
        self.assertEqual(
            term_with_descendant_ids(self.quarter.pk),
            {self.quarter.pk, self.semester.pk, self.trimester.pk, self.block.pk})
        self.assertEqual(term_with_descendant_ids(str(self.spring.pk)), {self.spring.pk})
        self.assertEqual(term_with_descendant_ids('not-a-uuid'), set())
        self.assertEqual(term_with_descendant_ids(None), set())

    def test_descendants_take_one_query(self):
        with CaptureQueriesContext(connection) as queries:
            term_with_descendant_ids(self.quarter.pk)
        self.assertEqual(len(queries.captured_queries), 1)

    def test_filter_by_parent_includes_sub_term_rows(self):
        course = Course.objects.create(
            catalog_number='101', title='Intro',
            cohort=Cohort.objects.create(name='C', designator='C'))

        def section(term, number):
            return ClassSection.objects.create(
                course=course, term=term, class_number=number, section_number='001')

        on_semester = section(self.semester, '1')
        on_block = section(self.block, '2')
        on_spring = section(self.spring, '3')

        by_parent = filter_by_term(ClassSection.objects.all(), self.quarter.pk)
        self.assertEqual(set(by_parent), {on_semester, on_block})
        by_leaf = filter_by_term(ClassSection.objects.all(), str(self.spring.pk))
        self.assertEqual(list(by_leaf), [on_spring])
        self.assertFalse(filter_by_term(ClassSection.objects.all(), 'junk').exists())
