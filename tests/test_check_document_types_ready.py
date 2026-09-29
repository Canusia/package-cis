"""check_document_types_ready: read-only go/no-go for #47.

#47 makes CourseDocumentRequirement.document_type required and drops the legacy
string columns, which loses data on any tenant where requirements are still
unlinked. The command reports what would block it and changes nothing.
"""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from cis.models.course import (
    Campus, Cohort, Course, CourseDocumentRequirement, DocumentType,
)


class CheckDocumentTypesReadyTests(TestCase):
    def setUp(self):
        self.campus = Campus.objects.create(name='Main', code='MAIN')
        self.cohort = Cohort.objects.create(name='C', designator='C')
        self.course = Course.objects.create(
            catalog_number='101', title='A', cohort=self.cohort, campus=self.campus)

    def _run(self, *args):
        out = StringIO()
        call_command('check_document_types_ready', *args, stdout=out)
        return out.getvalue()

    def test_not_ready_lists_each_blocker(self):
        Course.objects.create(catalog_number='102', title='B', cohort=self.cohort)
        CourseDocumentRequirement.objects.create(course=self.course, document='transcript')

        report = self._run()

        self.assertIn('NOT READY', report)
        self.assertIn('document types: 0', report)
        self.assertIn('requirements without a document type: 1', report)
        self.assertIn('courses without a campus: 1', report)

    def test_ready_when_everything_is_linked(self):
        doc_type = DocumentType.objects.create(
            code='transcript', label='Transcript', campus=self.campus)
        CourseDocumentRequirement.objects.create(
            course=self.course, document='transcript', document_type=doc_type)

        report = self._run()

        self.assertIn('READY', report)
        self.assertNotIn('NOT READY', report)

    def test_fail_flag_raises_when_not_ready(self):
        with self.assertRaises(CommandError):
            self._run('--fail-if-not-ready')

    def test_changes_nothing(self):
        CourseDocumentRequirement.objects.create(course=self.course, document='transcript')
        before = (DocumentType.objects.count(),
                  list(CourseDocumentRequirement.objects.values_list('document', 'document_type')))
        self._run()
        after = (DocumentType.objects.count(),
                 list(CourseDocumentRequirement.objects.values_list('document', 'document_type')))
        self.assertEqual(before, after)
