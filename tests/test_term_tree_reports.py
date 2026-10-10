"""Report term pickers render the tree and a parent includes its sub-terms."""
import importlib
import pathlib
import re

from django.test import TestCase

from cis.reports.detailed_students_with_class import detailed_students_with_class
from cis.tests.term_tree_fixtures import TermTreeFixtureMixin

REPORTS = [
    'transactions', 'ferpa_export', 'missing_parent_consent', 'students_by_date',
    'supporting_doc_export', 'recommendation_export', 'teacher_syllabi_status',
    'detailed_students_with_class', 'class_roster', 'class_export',
    'teacher_export', 'teacher_course_certificate',
]
REPORTS_DIR = pathlib.Path(importlib.import_module('cis.reports').__file__).parent


class ReportTermTreeTests(TermTreeFixtureMixin, TestCase):
    def test_every_report_picker_is_tree_ordered(self):
        for name in REPORTS:
            with self.subTest(report=name):
                cls = getattr(importlib.import_module(f'cis.reports.{name}'), name)
                form = cls()
                field = form.fields.get('term') or form.fields.get('terms')
                ids = [str(v) for v, _ in field.choices if v != '']
                self.assertEqual(
                    ids.index(str(self.quarter.pk)) + 1, ids.index(str(self.semester.pk)))

    def test_detailed_students_parent_includes_sub_terms(self):
        qs = detailed_students_with_class().get_result({
            'term': [str(self.quarter.pk)],
            'status': ['registered'],
            'campus': [str(self.campus.pk)],
        }, user=self.ce)
        self.assertEqual({r.class_section.term.label for r in qs}, self.fall_labels())

    def test_no_report_filters_on_raw_term_ids(self):
        """Every term `__in` lookup in a report goes through expand_term_ids."""
        pattern = re.compile(r'term(?:__id|_id)__in=(?!expand_term_ids\()')
        for name in REPORTS:
            with self.subTest(report=name):
                source = (REPORTS_DIR / f'{name}.py').read_text()
                self.assertIsNone(pattern.search(source), pattern.search(source))
