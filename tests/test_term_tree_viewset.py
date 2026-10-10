"""TermViewSet exposes tree_position / tree_depth for the terms table."""
from django.test import TestCase

from cis.serializers.term import TermSerializer
from cis.tests.term_tree_fixtures import TermTreeFixtureMixin, run_viewset
from cis.views.term import TermViewSet


class TermViewSetTreeTests(TermTreeFixtureMixin, TestCase):
    def test_tree_order_and_depth(self):
        qs = run_viewset(TermViewSet, self.ce).filter(academic_year=self.ay)
        rows = [(t.label, t.tree_depth) for t in qs.order_by('tree_position')]
        self.assertEqual(rows, [
            ('Fall Quarter', 0), ('Fall Semester', 1), ('Fall Trimester', 1), ('Spring', 0)])

    def test_search_keeps_consistent_order(self):
        qs = run_viewset(TermViewSet, self.ce).filter(label__icontains='Fall')
        self.assertEqual([t.label for t in qs.order_by('tree_position')],
                         ['Fall Quarter', 'Fall Semester', 'Fall Trimester'])

    def test_academic_year_filter_still_works(self):
        qs = run_viewset(TermViewSet, self.ce, academic_year=str(self.ay.pk))
        self.assertEqual(qs.count(), 4)

    def test_serializer_exposes_tree_fields(self):
        term = run_viewset(TermViewSet, self.ce).get(pk=self.semester.pk)
        data = TermSerializer(term).data
        self.assertEqual(data['tree_depth'], 1)
        self.assertIsInstance(data['tree_position'], int)

    def test_plain_term_serializes_without_tree_fields(self):
        data = TermSerializer(self.semester).data
        self.assertNotIn('tree_depth', data)
