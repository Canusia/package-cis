"""CE term dropdowns render the tree; the high schools picker keeps parents."""
import re

from django.test import TestCase
from django.template.loader import render_to_string

from cis.models.term import Term
from cis.tests.term_tree_fixtures import TermTreeFixtureMixin

TEMPLATES = [
    'cis/students/index.html', 'cis/registrations/index.html',
    'cis/students/recommendations.html', 'cis/students/faa_index.html',
    'cis/sections/index.html', 'cis/drop_wd/index.html',
    'cis/highschools/index.html', 'cis/course/campus.html',
    'cis/faculty/tabs/_class_sections.html', 'cis/students/tabs/_agreements.html',
    'cis/students/tabs/_parent_consents.html', 'cis/students/_hs_uploads_tab.html',
]
UNTOUCHED = [
    'cis/sections/class_section_search.html',
    'cis/sections/class_section_search_online.html',
]


def _template_source(name):
    from django.template import engines
    return engines['django'].engine.get_template(name).source


class TemplateLoopTests(TestCase):
    def test_every_term_loop_is_tree_ordered(self):
        for name in TEMPLATES:
            with self.subTest(template=name):
                src = _template_source(name)
                self.assertIn('{% load term_tree %}', src)
                self.assertNotRegex(src, r'{%\s*for \w+ in terms\s*%}')
                self.assertRegex(src, r'{%\s*for \w+ in terms\|term_tree\s*%}')
                self.assertIn('|term_indent }}', src)

    def test_class_selection_templates_untouched(self):
        for name in UNTOUCHED:
            with self.subTest(template=name):
                self.assertNotIn('term_tree', _template_source(name))


class AgreementsRenderTests(TermTreeFixtureMixin, TestCase):
    def test_sub_term_option_is_indented_under_parent(self):
        html = render_to_string('cis/students/tabs/_agreements.html', {
            'terms': Term.objects.filter(academic_year=self.ay).order_by('-code'),
            'record': self.registrations['Spring'].student,
        })
        options = re.findall(r'<option value="([^"]+)">([^<]*)</option>', html)
        ids = [o[0] for o in options]
        self.assertLess(ids.index(str(self.quarter.pk)), ids.index(str(self.semester.pk)))
        semester_label = dict(options)[str(self.semester.pk)]
        self.assertTrue(semester_label.startswith('&nbsp;&nbsp;&nbsp;Fall Semester'))


class HighSchoolsIndexTests(TermTreeFixtureMixin, TestCase):
    def test_highschools_index_lists_parent_of_used_sub_term(self):
        self.client.force_login(self.ce)
        response = self.client.get('/ce/highschools/')
        self.assertEqual(response.status_code, 200)
        listed = {t.pk for t in response.context['terms']}
        self.assertIn(self.quarter.pk, listed)   # no sections of its own
        self.assertIn(self.semester.pk, listed)
