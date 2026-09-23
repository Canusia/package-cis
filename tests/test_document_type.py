"""The DocumentType vocabulary table.

Guards the things that would silently break:
  - the same code may exist once per campus, but never twice in one campus;
  - two legacy null-campus rows with the same code are refused (Postgres
    treats NULLs as distinct, so a plain unique_together would allow them);
  - normalize() accepts a code or a label, case-insensitively.
"""
import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from cis.models.course import Campus, DocumentType


def _sfx():
    return uuid.uuid4().hex[:8]


class DocumentTypeConstraintTests(TestCase):
    def setUp(self):
        self.campus_a = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B{_sfx()}', code=f'B{_sfx()}')

    def test_same_code_allowed_once_per_campus(self):
        DocumentType.objects.create(
            code='transcript', label='HS Transcript', campus=self.campus_a)
        DocumentType.objects.create(
            code='transcript', label='Transcript', campus=self.campus_b)

        self.assertEqual(DocumentType.objects.filter(code='transcript').count(), 2)

    def test_duplicate_code_in_same_campus_refused(self):
        DocumentType.objects.create(
            code='transcript', label='HS Transcript', campus=self.campus_a)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentType.objects.create(
                    code='transcript', label='Other', campus=self.campus_a)

    def test_duplicate_code_with_null_campus_refused(self):
        """The case a plain unique_together would silently allow."""
        DocumentType.objects.create(code='transcript', label='HS Transcript')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentType.objects.create(code='transcript', label='Other')


class DocumentTypeNormalizeTests(TestCase):
    def setUp(self):
        self.campus = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.dt = DocumentType.objects.create(
            code='tsi', label='TSI Assessment', campus=self.campus)

    def test_matches_code_case_insensitively(self):
        self.assertEqual(DocumentType.normalize('TSI', campus=self.campus), self.dt)

    def test_matches_label_case_insensitively(self):
        self.assertEqual(
            DocumentType.normalize('tsi assessment', campus=self.campus), self.dt)

    def test_returns_none_when_unrecognised(self):
        self.assertIsNone(DocumentType.normalize('Nonsense', campus=self.campus))

    def test_returns_none_for_blank(self):
        self.assertIsNone(DocumentType.normalize('', campus=self.campus))
        self.assertIsNone(DocumentType.normalize(None, campus=self.campus))
