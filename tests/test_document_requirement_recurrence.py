"""#44: CourseDocumentRequirement.recurrence and satisfied_for().

Decisions pinned here (agreed on #44):
  Q1 no "per registration" option; per_term is the default;
  Q2 satisfaction is student-scoped -- an upload satisfies every course's
     requirement for the same DocumentType;
  Q3 uploads made before the requirement existed count;
  Q4 only uploads whose status is in support_docs' satisfying statuses count,
     and a blank setting means any status.
"""
import uuid
from unittest import mock

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from cis.models.course import (
    Campus, Cohort, Course, CourseDocumentRequirement, DocumentType,
)
from cis.models.customuser import CustomUser
from cis.models.settings import Setting
from cis.models.student import Student, StudentSupportingDocument
from cis.models.term import AcademicYear, Term


def _sfx():
    return uuid.uuid4().hex[:8]


class RecurrenceFieldTests(TestCase):
    def test_default_is_per_term(self):
        field = CourseDocumentRequirement._meta.get_field('recurrence')
        self.assertEqual(field.default, 'per_term')

    def test_choices_are_the_fixed_enum(self):
        """Code branches on recurrence, so it must not be tenant-overridable."""
        field = CourseDocumentRequirement._meta.get_field('recurrence')
        self.assertEqual(
            [code for code, _ in field.choices],
            ['per_term', 'per_academic_year', 'once'])
        with mock.patch(
                'cis.services.tenant_services.get_tenant_override',
                side_effect=AssertionError('recurrence must not be overridable')):
            CourseDocumentRequirement._meta.get_field('recurrence').choices


class SatisfiedForTests(TestCase):
    def setUp(self):
        patcher = mock.patch(
            'cis.storage_backend.PrivateMediaStorage._save',
            side_effect=lambda name, content: name)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.campus = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        self.transcript = DocumentType.objects.create(
            code='transcript', label='Transcript', campus=self.campus)
        self.shots = DocumentType.objects.create(
            code='shot_record', label='Immunization Record', campus=self.campus)

        ay1 = AcademicYear.objects.create(name=f'AY1{_sfx()}', campus=self.campus)
        ay2 = AcademicYear.objects.create(name=f'AY2{_sfx()}', campus=self.campus)
        self.fall = self._term(ay1)
        self.spring = self._term(ay1)
        self.next_fall = self._term(ay2)

        cohort = Cohort.objects.create(name=f'C{_sfx()}')
        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort, campus=self.campus)
        self.course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=cohort, campus=self.campus)

        Group.objects.get_or_create(name='student')
        email = f'{_sfx()}@example.com'
        user = CustomUser.objects.create_user(
            username=email, email=email, password='x')
        self.student = Student.objects.create(user=user)

    def _term(self, academic_year):
        return Term.objects.create(
            academic_year=academic_year, code=f'T{_sfx()}', label=f'L{_sfx()}')

    def _requirement(self, recurrence, course=None, document_type=None):
        document_type = document_type or self.transcript
        return CourseDocumentRequirement.objects.create(
            course=course or self.course_a, document=document_type.code,
            document_type=document_type, recurrence=recurrence)

    def _upload(self, term, document_type=None, status=''):
        return StudentSupportingDocument.objects.create(
            term=term, student=self.student,
            media=SimpleUploadedFile('doc.pdf', b'contents'),
            document_type_ref=document_type or self.transcript, status=status)

    def _set_satisfying_statuses(self, statuses):
        Setting.objects.update_or_create(
            key='cis.settings.support_docs',
            defaults={'value': {'satisfying_statuses': statuses}})

    # -- windows ----------------------------------------------------------

    def test_per_term_needs_the_same_term(self):
        req = self._requirement('per_term')
        self._upload(self.fall)
        self.assertTrue(req.satisfied_for(self.student, self.fall))
        self.assertFalse(req.satisfied_for(self.student, self.spring))

    def test_per_academic_year_covers_every_term_in_the_year(self):
        req = self._requirement('per_academic_year')
        self._upload(self.fall)
        self.assertTrue(req.satisfied_for(self.student, self.spring))
        self.assertFalse(req.satisfied_for(self.student, self.next_fall))

    def test_once_covers_every_term(self):
        req = self._requirement('once')
        self._upload(self.fall)
        self.assertTrue(req.satisfied_for(self.student, self.next_fall))

    def test_no_upload_is_not_satisfied(self):
        for recurrence in ('per_term', 'per_academic_year', 'once'):
            req = self._requirement(recurrence, course=Course.objects.create(
                catalog_number=_sfx()[:4], title='X',
                cohort=self.course_a.cohort, campus=self.campus))
            self.assertFalse(req.satisfied_for(self.student, self.fall))

    def test_other_document_type_does_not_count(self):
        req = self._requirement('once')
        self._upload(self.fall, document_type=self.shots)
        self.assertFalse(req.satisfied_for(self.student, self.fall))

    def test_other_students_upload_does_not_count(self):
        req = self._requirement('once')
        email = f'{_sfx()}@example.com'
        other = Student.objects.create(user=CustomUser.objects.create_user(
            username=email, email=email, password='x'))
        StudentSupportingDocument.objects.create(
            term=self.fall, student=other,
            media=SimpleUploadedFile('doc.pdf', b'contents'),
            document_type_ref=self.transcript)
        self.assertFalse(req.satisfied_for(self.student, self.fall))

    # -- decisions --------------------------------------------------------

    def test_q2_one_upload_satisfies_every_course(self):
        req_a = self._requirement('per_term', course=self.course_a)
        req_b = self._requirement('per_term', course=self.course_b)
        self._upload(self.fall)
        self.assertTrue(req_a.satisfied_for(self.student, self.fall))
        self.assertTrue(req_b.satisfied_for(self.student, self.fall))

    def test_q3_upload_older_than_the_requirement_counts(self):
        self._upload(self.fall)
        req = self._requirement('once')
        self.assertTrue(req.satisfied_for(self.student, self.next_fall))

    def test_q4_blank_setting_means_any_status(self):
        req = self._requirement('once')
        self._upload(self.fall, status='Rejected')
        self.assertTrue(req.satisfied_for(self.student, self.fall))

    def test_q4_only_satisfying_statuses_count(self):
        self._set_satisfying_statuses(['Reviewed'])
        req = self._requirement('once')
        self._upload(self.fall, status='Rejected')
        self.assertFalse(req.satisfied_for(self.student, self.fall))
        self._upload(self.fall, status='Reviewed')
        self.assertTrue(req.satisfied_for(self.student, self.fall))

    def test_requirement_without_document_type_is_not_satisfied(self):
        req = CourseDocumentRequirement.objects.create(
            course=self.course_a, document='transcript', recurrence='once')
        self._upload(self.fall)
        self.assertFalse(req.satisfied_for(self.student, self.fall))


class RecurrenceFormTests(TestCase):
    def setUp(self):
        self.campus = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        cohort = Cohort.objects.create(name=f'C{_sfx()}')
        self.course = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort, campus=self.campus,
            status='Active')
        self.req = CourseDocumentRequirement.objects.create(
            course=self.course, document='transcript', recurrence='per_term')

    def test_add_form_passes_recurrence_through(self):
        from cis.forms.course import AddCourseDocumentRequirementForm
        from cis.models.course import course_document_choices
        document = course_document_choices()[0][0]
        other = Course.objects.create(
            catalog_number='102', title='B', cohort=self.course.cohort,
            campus=self.campus, status='Active')
        form = AddCourseDocumentRequirementForm(data={
            'courses': [other.id], 'document': document, 'required': '1',
            'status': 'Active', 'recurrence': 'once',
            'action': 'add_course_doc_requirement',
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(
            CourseDocumentRequirement.objects.get(course=other).recurrence, 'once')

    def _bulk(self, recurrence):
        from django.http import QueryDict
        from cis.forms.course import BulkCourseDocumentRequirementUpdateForm
        data = QueryDict(mutable=True)
        data.setlist('record_ids', [str(self.req.id)])
        data.update({'new_status': 'Active', 'new_required': '1',
                     'new_recurrence': recurrence,
                     'action': 'update_course_doc_requirements'})
        form = BulkCourseDocumentRequirementUpdateForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.req.refresh_from_db()

    def test_bulk_update_sets_recurrence(self):
        self._bulk('per_academic_year')
        self.assertEqual(self.req.recurrence, 'per_academic_year')

    def test_bulk_update_keep_current_leaves_it(self):
        self._bulk('')
        self.assertEqual(self.req.recurrence, 'per_term')


class SatisfyingStatusesSettingTests(TestCase):
    def test_round_trip_and_blank_default(self):
        from django.test import RequestFactory
        from cis.settings.support_docs import support_docs
        Setting.objects.filter(key=support_docs.key).delete()
        self.assertIsNone(support_docs.get_satisfying_statuses())

        form = support_docs(RequestFactory().get('/?report_id=x'), data={
            'email_enabled': 'No', 'satisfying_statuses': 'Reviewed\n\n Approved ',
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        form.run_record()
        self.assertEqual(
            support_docs.get_satisfying_statuses(), ['Reviewed', 'Approved'])
        self.assertEqual(
            support_docs.from_db()['satisfying_statuses'], 'Reviewed\nApproved')

        form = support_docs(RequestFactory().get('/?report_id=x'), data={
            'email_enabled': 'No', 'satisfying_statuses': '',
        })
        self.assertTrue(form.is_valid())
        form.run_record()
        self.assertIsNone(support_docs.get_satisfying_statuses())


class RecurrenceEditFormFallbackTests(TestCase):
    def test_post_without_recurrence_keeps_the_stored_value(self):
        """A POST that predates #44 must not reset the value to per_term."""
        from cis.forms.course import CourseDocumentRequirementForm
        campus = Campus.objects.create(name=f'A{_sfx()}', code=f'A{_sfx()}')
        course = Course.objects.create(
            catalog_number='101', title='A',
            cohort=Cohort.objects.create(name=f'C{_sfx()}'), campus=campus)
        req = CourseDocumentRequirement.objects.create(
            course=course, document='transcript', recurrence='once')
        form = CourseDocumentRequirementForm(data={
            'document': 'transcript', 'status': 'Active', 'required': '1',
        }, instance=req, course=course)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        req.refresh_from_db()
        self.assertEqual(req.recurrence, 'once')
