"""cis.templatetags.term_tree: tree-ordered template loops."""
from django.template import Context, Template
from django.test import TestCase

from cis.models.term import Term
from cis.tests.term_tree_fixtures import TermTreeFixtureMixin


class TermTreeFilterTests(TermTreeFixtureMixin, TestCase):
    def render(self, terms):
        return Template(
            '{% load term_tree %}{% for t in terms|term_tree %}'
            '[{{ t|term_indent }}{{ t.label }}]{% endfor %}'
        ).render(Context({'terms': terms}))

    def test_children_follow_parent_with_indent(self):
        out = self.render(Term.objects.filter(academic_year=self.ay).order_by('-code'))
        self.assertEqual(out, (
            '[Fall Quarter]'
            '[&nbsp;&nbsp;&nbsp;Fall Semester]'
            '[&nbsp;&nbsp;&nbsp;Fall Trimester]'
            '[Spring]'))

    def test_missing_or_empty_terms_render_nothing(self):
        self.assertEqual(self.render(None), '')
        self.assertEqual(self.render(''), '')
        self.assertEqual(self.render(Term.objects.none()), '')

    def test_same_queryset_can_be_looped_twice(self):
        qs = Term.objects.filter(academic_year=self.ay).order_by('-code')
        self.assertEqual(self.render(qs), self.render(qs))
