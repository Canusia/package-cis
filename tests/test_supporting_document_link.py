"""#50: uploads are linked to their DocumentType when saved.

Before #50 only `init_document_types` ever set
StudentSupportingDocument.document_type_ref, so every upload made after a
tenant seeded stayed unlinked. save() now resolves the free-text type against
the row's own campus (term.academic_year.campus), with the same rules as the
command: own campus first, then the unassigned (null-campus) vocabulary, never
another campus's.
"""
import uuid
from unittest import mock

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from cis.models.course import Campus, DocumentType
from cis.models.customuser import CustomUser
from cis.models.student import Student, StudentSupportingDocument
from cis.models.term import AcademicYear, Term


def _sfx():
    return uuid.uuid4().hex[:8]


class DocumentTypeResolveTests(TestCase):
    def setUp(self):
        self.campus_a = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B{_sfx()}', code=f'B{_sfx()}')

    def test_prefers_own_campus_then_unassigned(self):
        unassigned = DocumentType.objects.create(code='tsi', label='TSI')
        self.assertEqual(DocumentType.resolve('TSI', self.campus_a.pk), unassigned)

        own = DocumentType.objects.create(
            code='tsi', label='TSI', campus=self.campus_a)
        self.assertEqual(DocumentType.resolve('tsi', self.campus_a.pk), own)

    def test_never_uses_another_campus(self):
        DocumentType.objects.create(code='tsi', label='TSI', campus=self.campus_b)
        self.assertIsNone(DocumentType.resolve('tsi', self.campus_a.pk))

    def test_campus_less_uses_unassigned_only(self):
        DocumentType.objects.create(code='tsi', label='TSI', campus=self.campus_a)
        self.assertIsNone(DocumentType.resolve('tsi', None))
        unassigned = DocumentType.objects.create(code='tsi', label='TSI')
        self.assertEqual(DocumentType.resolve('tsi', None), unassigned)

    def test_code_beats_another_types_label(self):
        by_code = DocumentType.objects.create(
            code='transcript', label='HS Transcript', campus=self.campus_a)
        DocumentType.objects.create(
            code='hs_transcript', label='Transcript', campus=self.campus_a)
        self.assertEqual(
            DocumentType.resolve('Transcript', self.campus_a.pk), by_code)

    def test_ambiguous_label_returns_none(self):
        DocumentType.objects.create(
            code='one', label='Transcript', campus=self.campus_a)
        DocumentType.objects.create(
            code='two', label='transcript', campus=self.campus_a)
        self.assertIsNone(DocumentType.resolve('TRANSCRIPT', self.campus_a.pk))

    def test_blank_returns_none(self):
        self.assertIsNone(DocumentType.resolve('  ', self.campus_a.pk))
        self.assertIsNone(DocumentType.resolve(None, self.campus_a.pk))


class UploadLinkedOnSaveTests(TestCase):
    """`media` is bound to S3-backed storage; patch `_save` as
    test_document_type.py does."""

    def setUp(self):
        patcher = mock.patch(
            'cis.storage_backend.PrivateMediaStorage._save',
            side_effect=lambda name, content: name)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.campus_a = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B{_sfx()}', code=f'B{_sfx()}')
        self.dt_a = DocumentType.objects.create(
            code='transcript', label='HS Transcript', campus=self.campus_a)

        Group.objects.get_or_create(name='student')
        email = f'{_sfx()}@example.com'
        user = CustomUser.objects.create_user(
            username=email, email=email, password='x')
        self.student = Student.objects.create(user=user)

    def _term(self, campus):
        academic_year = AcademicYear.objects.create(
            name=f'AY{_sfx()}', campus=campus)
        return Term.objects.create(
            academic_year=academic_year, code=f'T{_sfx()}', label=f'L{_sfx()}')

    def _doc(self, term, document_type, **kwargs):
        return StudentSupportingDocument.objects.create(
            term=term, student=self.student,
            media=SimpleUploadedFile('doc.pdf', b'contents'),
            document_type=document_type, **kwargs)

    def test_upload_after_seeding_is_linked(self):
        doc = self._doc(self._term(self.campus_a), 'HS Transcript')
        doc.refresh_from_db()
        self.assertEqual(doc.document_type_ref, self.dt_a)
        self.assertEqual(doc.document_type, 'HS Transcript')

    def test_never_linked_to_another_campus_type(self):
        doc = self._doc(self._term(self.campus_b), 'HS Transcript')
        doc.refresh_from_db()
        self.assertIsNone(doc.document_type_ref)

    def test_campus_less_term_falls_back_to_unassigned(self):
        unassigned = DocumentType.objects.create(code='tsi', label='TSI')
        doc = self._doc(self._term(None), 'tsi')
        doc.refresh_from_db()
        self.assertEqual(doc.document_type_ref, unassigned)

    def test_unmatched_value_left_unlinked_and_untouched(self):
        doc = self._doc(self._term(self.campus_a), 'Some Unknown Type')
        doc.refresh_from_db()
        self.assertIsNone(doc.document_type_ref)
        self.assertEqual(doc.document_type, 'Some Unknown Type')

    def test_update_fields_save_persists_the_link(self):
        doc = self._doc(self._term(self.campus_a), '')
        doc.document_type = 'transcript'
        doc.save(update_fields=['document_type'])
        doc.refresh_from_db()
        self.assertEqual(doc.document_type_ref, self.dt_a)

    def test_no_lookup_when_ref_already_set(self):
        doc = self._doc(self._term(self.campus_a), 'HS Transcript',
                        document_type_ref=self.dt_a)
        doc.description = 'edited'
        # An existing status-tracking signal already reads the row, so count
        # the tables touched rather than the queries.
        with CaptureQueriesContext(connection) as ctx:
            doc.save(update_fields=['description'])
        sql = ' '.join(q['sql'] for q in ctx.captured_queries)
        self.assertNotIn('cis_documenttype', sql)
        self.assertNotIn('cis_term', sql)
