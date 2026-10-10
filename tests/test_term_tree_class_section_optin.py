"""ClassSectionViewSet: sub-terms only behind include_sub_terms=1.

The student class-selection page and the class lookup fragment call this
endpoint without the flag; their results must not change.
"""
from unittest import mock

from django.test import TestCase

from cis.models.term import Term
from cis.tests.term_tree_fixtures import TermTreeFixtureMixin, run_viewset
from cis.views.section import ClassSectionViewSet


class ClassSectionOptInTests(TermTreeFixtureMixin, TestCase):
    def labels(self, **params):
        return {s.term.label for s in run_viewset(ClassSectionViewSet, self.ce, **params)}

    def test_parent_without_flag_is_exact_as_today(self):
        self.assertEqual(self.labels(term=str(self.quarter.pk)), set())

    def test_sub_term_without_flag_is_exact(self):
        self.assertEqual(self.labels(term=str(self.semester.pk)), {'Fall Semester'})

    def test_parent_with_flag_includes_sub_terms(self):
        self.assertEqual(
            self.labels(term=str(self.quarter.pk), include_sub_terms='1'),
            self.fall_labels())

    def test_registration_terms_branch_unchanged(self):
        reg_terms = Term.objects.filter(pk__in=[self.quarter.pk, self.spring.pk])
        with mock.patch('cis.views.section.get_registration_terms', return_value=reg_terms):
            self.assertEqual(self.labels(term='registration_terms'), {'Spring'})
            self.assertEqual(
                self.labels(term='registration_terms', include_sub_terms='1'), {'Spring'})

    def test_class_number_branch_unchanged(self):
        number = self.sections['Fall Semester'].class_number
        self.assertEqual(
            self.labels(term=str(self.quarter.pk), class_number=number,
                        include_sub_terms='1'),
            set())
