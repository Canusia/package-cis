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


from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from cis.models.settings import Setting


class InitDocumentTypesTests(TestCase):
    def setUp(self):
        self.campus_a = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B{_sfx()}', code=f'B{_sfx()}')

    def _run(self, **kwargs):
        out = StringIO()
        call_command('init_document_types', stdout=out, stderr=out, **kwargs)
        return out.getvalue()

    def test_seeds_one_copy_per_campus(self):
        self._run()

        for campus in (self.campus_a, self.campus_b):
            codes = set(DocumentType.objects.filter(campus=campus)
                        .values_list('code', flat=True))
            self.assertIn('transcript', codes)

    def test_is_idempotent(self):
        self._run()
        before = DocumentType.objects.count()

        self._run()

        self.assertEqual(DocumentType.objects.count(), before)

    def test_dry_run_writes_nothing(self):
        self._run(dry_run=True)

        self.assertEqual(DocumentType.objects.count(), 0)

    def test_campus_flag_restricts_seeding(self):
        self._run(campus=self.campus_a.code)

        self.assertGreater(DocumentType.objects.filter(campus=self.campus_a).count(), 0)
        self.assertEqual(DocumentType.objects.filter(campus=self.campus_b).count(), 0)

    def test_unmatched_setting_value_raises(self):
        """A support_docs type that matches no known code must be reported,
        never silently dropped or silently invented."""
        Setting.objects.update_or_create(
            key='cis.settings.support_docs',
            defaults={'value': {'types': ['Completely Unknown Doc']}})

        with self.assertRaises(CommandError) as ctx:
            self._run()

        self.assertIn('Completely Unknown Doc', str(ctx.exception))

    def test_backfills_requirement_fk_from_legacy_code(self):
        cohort = Cohort.objects.create(name=f'C{_sfx()}')
        course = Course.objects.create(
            name='C', catalog_number=f'X{_sfx()}',
            cohort=cohort, campus=self.campus_a)
        req = CourseDocumentRequirement.objects.create(
            course=course, document='transcript')

        self._run()
        req.refresh_from_db()

        self.assertIsNotNone(req.document_type)
        self.assertEqual(req.document_type.code, 'transcript')
        self.assertEqual(req.document_type.campus, self.campus_a)


class InitDocumentTypesUploadBackfillTests(TestCase):
    """Coverage for the fix-round-1 gap: uploads must resolve against their
    OWN term's academic-year campus, never a null-campus type that can never
    exist (the command only ever creates per-campus rows), and never a
    different campus's type.
    """

    def setUp(self):
        patcher = mock.patch(
            'cis.storage_backend.PrivateMediaStorage._save',
            side_effect=lambda name, content: name)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.campus_a = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B{_sfx()}', code=f'B{_sfx()}')

        Group.objects.get_or_create(name='student')
        email = f'{_sfx()}@example.com'
        user = CustomUser.objects.create_user(
            username=email, email=email, password='x')
        self.student = Student.objects.create(user=user)

    def _run(self, **kwargs):
        out = StringIO()
        call_command('init_document_types', stdout=out, stderr=out, **kwargs)
        return out.getvalue()

    def _term(self, campus):
        academic_year = AcademicYear.objects.create(
            name=f'AY{_sfx()}', campus=campus)
        return Term.objects.create(
            academic_year=academic_year, code=f'T{_sfx()}', label=f'L{_sfx()}')

    def _doc(self, term, document_type):
        return StudentSupportingDocument.objects.create(
            term=term, student=self.student,
            media=SimpleUploadedFile('doc.pdf', b'contents'),
            document_type=document_type)

    def test_links_to_its_own_campus_type(self):
        term_a = self._term(self.campus_a)
        doc = self._doc(term_a, 'transcript')

        self._run()
        doc.refresh_from_db()

        self.assertIsNotNone(doc.document_type_ref)
        self.assertEqual(doc.document_type_ref.campus, self.campus_a)
        self.assertEqual(doc.document_type_ref.code, 'transcript')

    def test_never_links_to_a_different_campus_type(self):
        """A document's own campus (campus_a) has no matching type yet, while
        a DIFFERENT campus (campus_b) does. The backfill must leave the
        document unmatched rather than borrow campus_b's type -- wrong-campus
        is worse than no link. Once campus_a is seeded too, it links to
        campus_a's own type, never campus_b's."""
        term_a = self._term(self.campus_a)
        doc = self._doc(term_a, 'transcript')

        # Seed only campus_b's vocabulary (the --campus flag scopes the
        # seeding step; campus_a still has zero DocumentType rows).
        self._run(campus=self.campus_b.code)
        doc.refresh_from_db()
        self.assertIsNone(doc.document_type_ref)

        # Now seed every campus, including campus_a.
        self._run()
        doc.refresh_from_db()

        self.assertIsNotNone(doc.document_type_ref)
        self.assertEqual(doc.document_type_ref.campus, self.campus_a)

    def test_unmatched_free_text_left_alone(self):
        term_a = self._term(self.campus_a)
        doc = self._doc(term_a, 'Some Totally Unknown Type')

        self._run()
        doc.refresh_from_db()

        self.assertIsNone(doc.document_type_ref)
        self.assertEqual(doc.document_type, 'Some Totally Unknown Type')

    def test_relabeling_survives_reseeding(self):
        """code is the stable key; label is freely editable by a CE admin.
        Re-running the seed command must never clobber an edited label or
        create a duplicate row for the same (campus, code)."""
        self._run()

        dt = DocumentType.objects.get(code='transcript', campus=self.campus_a)
        dt.label = 'TSI Score'
        dt.save()

        self._run()

        dt.refresh_from_db()
        self.assertEqual(dt.label, 'TSI Score')
        self.assertEqual(
            DocumentType.objects.filter(
                code='transcript', campus=self.campus_a).count(),
            1)


class DocumentTypeDropdownScopeTests(TestCase):
    def setUp(self):
        self.campus_a = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B{_sfx()}', code=f'B{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'C{_sfx()}')
        self.course_a = Course.objects.create(
            name='A', catalog_number=f'A{_sfx()}',
            cohort=self.cohort, campus=self.campus_a)

        self.type_a = DocumentType.objects.create(
            code='transcript', label='A Transcript', campus=self.campus_a)
        self.type_b = DocumentType.objects.create(
            code='transcript', label='B Transcript', campus=self.campus_b)

    def test_form_offers_only_the_courses_campus_types(self):
        from cis.forms.course import CourseDocumentRequirementForm

        form = CourseDocumentRequirementForm(course=self.course_a)
        offered = set(form.fields['document_type'].queryset)

        self.assertIn(self.type_a, offered)
        self.assertNotIn(self.type_b, offered)

    def test_form_rejects_a_type_from_another_campus(self):
        from cis.forms.course import CourseDocumentRequirementForm

        form = CourseDocumentRequirementForm(
            course=self.course_a,
            data={'document_type': str(self.type_b.id),
                  'status': 'Active', 'required': '1'})

        self.assertFalse(form.is_valid())
        self.assertIn('document_type', form.errors)

    def test_inactive_types_are_not_offered(self):
        from cis.forms.course import CourseDocumentRequirementForm

        self.type_a.status = 'Inactive'
        self.type_a.save()

        form = CourseDocumentRequirementForm(course=self.course_a)

        self.assertNotIn(self.type_a, set(form.fields['document_type'].queryset))

    def test_form_constructible_without_a_course(self):
        """Falls back to self.instance.course.campus when no course kwarg
        is given -- callers that only pass instance= must keep working."""
        from cis.forms.course import CourseDocumentRequirementForm

        req = CourseDocumentRequirement.objects.create(
            course=self.course_a, document_type=self.type_a)

        form = CourseDocumentRequirementForm(instance=req)
        offered = set(form.fields['document_type'].queryset)

        self.assertIn(self.type_a, offered)
        self.assertNotIn(self.type_b, offered)


class AddCourseDocumentRequirementFormScopeTests(TestCase):
    def setUp(self):
        self.campus_a = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.campus_b = Campus.objects.create(name=f'B{_sfx()}', code=f'B{_sfx()}')
        self.cohort = Cohort.objects.create(name=f'C{_sfx()}')
        self.course_a = Course.objects.create(
            name='A', catalog_number=f'A{_sfx()}',
            cohort=self.cohort, campus=self.campus_a, status='Active')
        self.course_b = Course.objects.create(
            name='B', catalog_number=f'B{_sfx()}',
            cohort=self.cohort, campus=self.campus_b, status='Active')

        self.type_a = DocumentType.objects.create(
            code='transcript', label='A Transcript', campus=self.campus_a)

    def test_save_skips_courses_on_a_different_campus_than_the_type(self):
        from cis.forms.course import AddCourseDocumentRequirementForm

        form = AddCourseDocumentRequirementForm(data={
            'courses': [self.course_a.id, self.course_b.id],
            'document_type': str(self.type_a.id),
            'document': 'transcript',
            'required': '1',
            'status': 'Active',
            'action': 'add_course_doc_requirement',
        })

        self.assertTrue(form.is_valid(), form.errors)
        records = form.save()

        courses_saved = {r.course_id for r in records}
        self.assertIn(self.course_a.id, courses_saved)
        self.assertNotIn(self.course_b.id, courses_saved)
        self.assertEqual(form.skipped_courses, [self.course_b])

    def test_save_persists_the_chosen_document_type(self):
        from cis.forms.course import AddCourseDocumentRequirementForm

        form = AddCourseDocumentRequirementForm(data={
            'courses': [self.course_a.id],
            'document_type': str(self.type_a.id),
            'document': 'transcript',
            'required': '1',
            'status': 'Active',
            'action': 'add_course_doc_requirement',
        })

        self.assertTrue(form.is_valid(), form.errors)
        records = form.save()

        record = records[0]
        record.refresh_from_db()
        self.assertEqual(record.document_type, self.type_a)
        # The dual-write save() override (Task 4) keeps the legacy string in
        # sync with whatever FK was set.
        self.assertEqual(record.document, 'transcript')

    def test_save_with_no_document_type_does_not_clear_an_existing_fk(self):
        """document_type is optional on this bulk form. Leaving it blank on
        a later submission must not unlink a requirement that was already
        tied to a DocumentType -- an optional field must never be
        destructive just because it was left blank."""
        from cis.forms.course import AddCourseDocumentRequirementForm

        existing = CourseDocumentRequirement.objects.create(
            course=self.course_a, document='transcript',
            document_type=self.type_a, required='1', status='Active')

        form = AddCourseDocumentRequirementForm(data={
            'courses': [self.course_a.id],
            'document_type': '',
            'document': 'transcript',
            'required': '1',
            'status': 'Active',
            'action': 'add_course_doc_requirement',
        })

        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        existing.refresh_from_db()
        self.assertEqual(existing.document_type, self.type_a)
