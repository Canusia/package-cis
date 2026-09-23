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


from cis.models.course import Cohort, Course, CourseDocumentRequirement


class DualWriteTests(TestCase):
    def setUp(self):
        self.campus = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'C{_sfx()}')
        self.course = Course.objects.create(
            name='C', catalog_number=f'X{_sfx()}',
            cohort=self.cohort, campus=self.campus)
        self.dt = DocumentType.objects.create(
            code='transcript', label='HS Transcript', campus=self.campus)

    def test_setting_fk_syncs_the_legacy_string(self):
        req = CourseDocumentRequirement.objects.create(
            course=self.course, document_type=self.dt)

        req.refresh_from_db()
        self.assertEqual(req.document, 'transcript')

    def test_legacy_string_alone_still_works(self):
        """A tenant that never seeds must be completely unaffected."""
        req = CourseDocumentRequirement.objects.create(
            course=self.course, document='tsi')

        req.refresh_from_db()
        self.assertIsNone(req.document_type)
        self.assertEqual(req.document, 'tsi')

    def test_document_label_prefers_the_fk(self):
        req = CourseDocumentRequirement.objects.create(
            course=self.course, document_type=self.dt)

        self.assertEqual(req.document_label, 'HS Transcript')

    def test_document_label_falls_back_to_the_string(self):
        req = CourseDocumentRequirement.objects.create(
            course=self.course, document='transcript')

        self.assertEqual(req.document_label, 'High School Transcript')


from unittest import mock

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile

from cis.models.customuser import CustomUser
from cis.models.student import Student, StudentSupportingDocument
from cis.models.term import AcademicYear, Term


class StudentSupportingDocumentDualWriteTests(TestCase):
    """The `media` FileField is bound to a real S3-backed storage class, which
    has no bucket to talk to in this environment. Patch `_save` so these
    dual-write tests exercise the model layer without a live S3 dependency --
    the same gap `test_report_supporting_doc_export_campus.py` hits.
    """

    def setUp(self):
        patcher = mock.patch(
            'cis.storage_backend.PrivateMediaStorage._save',
            side_effect=lambda name, content: name)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.campus = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.dt = DocumentType.objects.create(
            code='transcript', label='HS Transcript', campus=self.campus)

        academic_year = AcademicYear.objects.create(name=f'AY{_sfx()}')
        self.term = Term.objects.create(
            academic_year=academic_year, code=f'T{_sfx()}', label=f'L{_sfx()}')

        Group.objects.get_or_create(name='student')
        email = f'{_sfx()}@example.com'
        user = CustomUser.objects.create_user(
            username=email, email=email, password='x')
        self.student = Student.objects.create(user=user)

    def _media(self):
        return SimpleUploadedFile('doc.pdf', b'contents')

    def test_setting_fk_syncs_the_legacy_label(self):
        doc = StudentSupportingDocument.objects.create(
            term=self.term, student=self.student, media=self._media(),
            document_type_ref=self.dt)

        doc.refresh_from_db()
        self.assertEqual(doc.document_type, 'HS Transcript')

    def test_legacy_string_alone_still_works(self):
        """A tenant that never seeds must be completely unaffected."""
        doc = StudentSupportingDocument.objects.create(
            term=self.term, student=self.student, media=self._media(),
            document_type='Transcript')

        doc.refresh_from_db()
        self.assertIsNone(doc.document_type_ref)
        self.assertEqual(doc.document_type, 'Transcript')
