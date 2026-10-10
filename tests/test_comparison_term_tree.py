"""Compare Terms: tree-ordered picker, a parent column rolls up its sub-terms."""
from django.test import RequestFactory, TestCase

from cis.models.term import Term
from cis.services.comparison import (
    build_compare_context, build_payload, get_dimension, parse_filters, run_metric,
)
from cis.tests.term_tree_fixtures import TermTreeFixtureMixin, make_registration


class CompareTermTreeTests(TermTreeFixtureMixin, TestCase):
    def filters(self, *terms, slug='term'):
        request = RequestFactory().get(f'/ce/api/comparison/{slug}/', {
            'id': [str(t.pk) for t in terms],
            'campus': [str(self.campus.pk)],
        })
        request.user = self.ce
        return parse_filters(request, get_dimension(slug))

    def totals(self, filters, key='registrations_by_status'):
        out = {}
        for row in run_metric(filters, key):
            out[row['dimension_id']] = out.get(row['dimension_id'], 0) + row['value']
        return out

    def test_picker_tree_order_with_depth(self):
        request = RequestFactory().get('/ce/terms/')
        request.user = self.ce
        records = [r for r in build_compare_context(request, 'term')['compare_records']
                   if r['id'] in {str(t.pk) for t in (self.quarter, self.semester,
                                                       self.trimester, self.spring)}]
        self.assertEqual([(r['id'], r['depth']) for r in records], [
            (str(self.quarter.pk), 0), (str(self.semester.pk), 1),
            (str(self.trimester.pk), 1), (str(self.spring.pk), 0)])

    def test_parent_column_sums_sub_terms(self):
        make_registration(self.sections['Fall Semester'])  # semester now has 2
        totals = self.totals(self.filters(self.quarter, self.spring))
        self.assertEqual(totals, {str(self.quarter.pk): 3, str(self.spring.pk): 1})

    def test_sub_term_alone_is_exact(self):
        self.assertEqual(self.totals(self.filters(self.semester)),
                         {str(self.semester.pk): 1})

    def test_parent_and_its_sub_term_each_correct(self):
        totals = self.totals(self.filters(self.quarter, self.semester))
        self.assertEqual(totals, {str(self.quarter.pk): 2, str(self.semester.pk): 1})

    def test_total_credits_rolls_up(self):
        rows = run_metric(self.filters(self.quarter), 'total_credits')
        self.assertEqual([(r['dimension_id'], r['value']) for r in rows],
                         [(str(self.quarter.pk), 6)])

    def test_parent_label_names_sub_term_count(self):
        labels = {d['id']: d['label'] for d in
                  build_payload(self.filters(self.quarter, self.spring))['dimensions']}
        self.assertEqual(labels[str(self.quarter.pk)], f'{self.quarter} (+2 sub-terms)')
        self.assertEqual(labels[str(self.spring.pk)], str(self.spring))

    def test_parent_label_singular_for_one_sub_term(self):
        Term.objects.create(academic_year=self.ay, code='291', label='Fall Block',
                            parent=self.semester)
        labels = {d['id']: d['label'] for d in
                  build_payload(self.filters(self.semester))['dimensions']}
        self.assertEqual(labels[str(self.semester.pk)], f'{self.semester} (+1 sub-term)')

    def test_academic_year_unchanged(self):
        totals = self.totals(self.filters(self.ay, slug='academic_year'))
        self.assertEqual(totals, {str(self.ay.pk): 3})
        self.assertFalse(get_dimension('academic_year').rollup)
