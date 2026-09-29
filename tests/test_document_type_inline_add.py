"""#45: add a new DocumentType from the Add Document Requirement modal.

AddCourseDocumentRequirementForm takes exactly one source for the document: a
legacy vocabulary code, an existing DocumentType, or a new type (label, code,
campus). A new type goes through DocumentTypeForm's rules (campus required and
limited to the user's campuses, no duplicate or shadowing code) and is created
in the same transaction as the requirements.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.forms.course import AddCourseDocumentRequirementForm
from cis.models.course import (
    Campus, Cohort, Course, CourseDocumentRequirement, DocumentType,
    course_document_choices,
)
from cis.models.customuser import CustomUser


def _sfx():
    return uuid.uuid4().hex[:8]


class InlineNewTypeTests(TestCase):
    def setUp(self):
        self.campus_a = Campus.objects.create(
            name=f'A{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        self.campus_b = Campus.objects.create(
            name=f'B{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        cohort = Cohort.objects.create(name=f'C{_sfx()}', designator='C')
        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort,
            campus=self.campus_a, status='Active')
        self.course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=cohort,
            campus=self.campus_b, status='Active')
        self.ce = CustomUser.objects.create_user(
            username=f'ce{_sfx()}', email=f'ce{_sfx()}@x.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.ce.campus = {'process_campus': [str(self.campus_a.id)]}
        self.ce.save()

    def _form(self, **overrides):
        data = {
            'courses': [self.course_a.id], 'required': '1', 'status': 'Active',
            'recurrence': 'once', 'action': 'add_course_doc_requirement',
            'new_type_label': 'Vaccination Card', 'new_type_code': 'vax_card',
            'new_type_campus': self.campus_a.id,
        }
        data.update(overrides)
        return AddCourseDocumentRequirementForm(data=data, user=self.ce)

    def test_new_type_is_created_and_used(self):
        form = self._form()
        self.assertTrue(form.is_valid(), form.errors)
        records = form.save()

        new_type = DocumentType.objects.get(code='vax_card', campus=self.campus_a)
        self.assertEqual(new_type.label, 'Vaccination Card')
        self.assertEqual(len(records), 1)
        req = CourseDocumentRequirement.objects.get(course=self.course_a)
        self.assertEqual(req.document_type, new_type)
        self.assertEqual(req.document, 'vax_card')

    def test_courses_on_other_campuses_are_skipped(self):
        form = self._form(courses=[self.course_a.id, self.course_b.id])
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(form.skipped_courses, [self.course_b])
        self.assertFalse(CourseDocumentRequirement.objects.filter(
            course=self.course_b).exists())

    def test_duplicate_code_on_the_campus_is_refused(self):
        DocumentType.objects.create(code='vax_card', label='Vax', campus=self.campus_a)
        form = self._form()
        self.assertFalse(form.is_valid())
        self.assertIn('new_type_code', form.errors)

    def test_another_users_campus_is_refused(self):
        form = self._form(new_type_campus=self.campus_b.id)
        self.assertFalse(form.is_valid())
        self.assertIn('new_type_campus', form.errors)
        self.assertFalse(DocumentType.objects.filter(code='vax_card').exists())

    def test_new_type_needs_label_code_and_campus(self):
        form = self._form(new_type_code='')
        self.assertFalse(form.is_valid())
        self.assertIn('new_type_code', form.errors)

    def test_existing_and_new_type_together_is_refused(self):
        existing = DocumentType.objects.create(
            code='transcript', label='Transcript', campus=self.campus_a)
        form = self._form(document_type=existing.id)
        self.assertFalse(form.is_valid())
        self.assertIn('document_type', form.errors)

    def test_nothing_chosen_is_refused(self):
        form = self._form(new_type_label='', new_type_code='', new_type_campus='')
        self.assertFalse(form.is_valid())
        self.assertIn('document', form.errors)

    def test_existing_type_alone_fills_the_legacy_code(self):
        existing = DocumentType.objects.create(
            code='transcript', label='Transcript', campus=self.campus_a)
        form = self._form(new_type_label='', new_type_code='', new_type_campus='',
                          document_type=existing.id)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        req = CourseDocumentRequirement.objects.get(course=self.course_a)
        self.assertEqual(req.document, 'transcript')
        self.assertEqual(req.document_type, existing)

    def test_legacy_code_alone_still_works(self):
        code = course_document_choices()[0][0]
        form = self._form(new_type_label='', new_type_code='', new_type_campus='',
                          document=code)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        req = CourseDocumentRequirement.objects.get(course=self.course_a)
        self.assertEqual(req.document, code)
        self.assertIsNone(req.document_type)
