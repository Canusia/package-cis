"""cis.services.term_hierarchy: parent/sub-term pickers and filters."""
from django import forms
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term
from cis.services.term_hierarchy import (
    apply_term_tree, descendant_groups, expand_term_ids, filter_by_term,
    term_ids_with_ancestors, term_tree, term_tree_choices,
    term_with_descendant_ids,
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


class TermIdHelperTests(TestCase):
    def setUp(self):
        ay = AcademicYear.objects.create(name='2027-2028')
        self.quarter = Term.objects.create(academic_year=ay, code='300', label='Q')
        self.semester = Term.objects.create(
            academic_year=ay, code='290', label='S', parent=self.quarter)
        self.block = Term.objects.create(
            academic_year=ay, code='270', label='B', parent=self.semester)
        self.spring = Term.objects.create(academic_year=ay, code='200', label='Sp')

    def test_descendant_groups_one_query(self):
        with CaptureQueriesContext(connection) as queries:
            groups = descendant_groups([self.quarter.pk, str(self.spring.pk)])
        self.assertEqual(len(queries.captured_queries), 1)
        self.assertEqual(groups, {
            self.quarter.pk: {self.quarter.pk, self.semester.pk, self.block.pk},
            self.spring.pk: {self.spring.pk},
        })

    def test_expand_term_ids_accepts_single_value_and_terms(self):
        self.assertEqual(expand_term_ids(str(self.semester.pk)),
                         {self.semester.pk, self.block.pk})
        self.assertEqual(expand_term_ids([self.semester, self.spring]),
                         {self.semester.pk, self.block.pk, self.spring.pk})

    def test_expand_term_ids_tolerates_junk(self):
        for junk in (None, '', 'nope', [], ['', None, 'x']):
            with self.subTest(junk=junk):
                self.assertEqual(expand_term_ids(junk), set())
        with CaptureQueriesContext(connection) as queries:
            expand_term_ids(['x'])
        self.assertEqual(len(queries.captured_queries), 0)

    def test_ancestors(self):
        self.assertEqual(term_ids_with_ancestors([self.block.pk]),
                         {self.block.pk, self.semester.pk, self.quarter.pk})
        self.assertEqual(term_ids_with_ancestors([self.spring]), {self.spring.pk})

    def test_apply_term_tree_single_keeps_empty_label_and_order(self):
        class F(forms.Form):
            term = forms.ModelChoiceField(queryset=Term.objects.none(), required=False)

        form = F()
        apply_term_tree(form.fields['term'], Term.objects.order_by('-code'))
        choices = list(form.fields['term'].choices)
        self.assertEqual(choices[0], ('', '---------'))
        self.assertEqual([c[0] for c in choices[1:5]], [
            str(self.quarter.pk), str(self.semester.pk),
            str(self.block.pk), str(self.spring.pk)])
        self.assertEqual(choices[3][1], '\xa0' * 6 + str(self.block))

    def test_apply_term_tree_multiple_has_no_blank_and_validates(self):
        class F(forms.Form):
            terms = forms.ModelMultipleChoiceField(queryset=Term.objects.none())

        form = F(data={'terms': [str(self.block.pk)]})
        apply_term_tree(form.fields['terms'], Term.objects.order_by('-code'))
        self.assertNotEqual(list(form.fields['terms'].choices)[0][0], '')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(list(form.cleaned_data['terms']), [self.block])

    def test_apply_term_tree_keeps_selected_value(self):
        class F(forms.Form):
            term = forms.ModelChoiceField(queryset=Term.objects.none())

        form = F(initial={'term': self.semester})
        apply_term_tree(form.fields['term'], Term.objects.order_by('-code'))
        html = str(form['term'])
        self.assertIn(f'value="{self.semester.pk}" selected', html)
