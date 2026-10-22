"""Missing supporting documents on the CE student Supporting Documents tab.

cis.services.document_requirements lists what a student's current courses
require and whether it has been received, using satisfied_for() for the
recurrence window and satisfying statuses. Off unless the support_docs
setting's show_missing_documents is Yes.
"""
import uuid
from unittest import mock

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import TestCase

from cis.models.course import (
    Campus, Cohort, Course, CourseDocumentRequirement, DocumentType,
)
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student, StudentSupportingDocument
from cis.models.term import AcademicYear, Term
from cis.services import document_requirements as dr
from cis.settings.support_docs import support_docs


def _sfx():
    return uuid.uuid4().hex[:8]


class MissingDocumentsTests(TestCase):
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

        ay = AcademicYear.objects.create(name=f'AY{_sfx()}', campus=self.campus)
        self.fall = Term.objects.create(academic_year=ay, code=f'T{_sfx()}', label='Fall')
        self.old = Term.objects.create(academic_year=ay, code=f'T{_sfx()}', label='Old')

        cohort = Cohort.objects.create(name=f'C{_sfx()}')
        self.course_a = Course.objects.create(
            catalog_number='101', title='Alpha', cohort=cohort, campus=self.campus)
        self.course_b = Course.objects.create(
            catalog_number='102', title='Beta', cohort=cohort, campus=self.campus)
        self.hs = HighSchool.objects.create(name=f'HS{_sfx()}')

        Group.objects.get_or_create(name='student')
        # Registration signals write a student note as the 'cron' user.
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': f'cron{_sfx()}@example.com'})
        email = f'{_sfx()}@example.com'
        user = CustomUser.objects.create_user(username=email, email=email, password='x')
        self.student = Student.objects.create(user=user, grade_level='11')

        self._enable()

    # -- fixtures -------------------------------------------------------------

    def _settings(self, **values):
        value = {'show_missing_documents': 'Yes'}
        value.update(values)
        Setting.objects.update_or_create(key=support_docs.key, defaults={'value': value})

    def _enable(self, **values):
        self._settings(**values)

    def _register(self, course, term=None, status='applied'):
        term = term or self.fall
        section = ClassSection.objects.create(
            class_number=f'CN{_sfx()}', section_number='01', term=term,
            registration_term=term, course=course, highschool=self.hs, status='A')
        return StudentRegistration.objects.create(
            student=self.student, class_section=section, status=status,
            status_changed_on={})

    def _require(self, course, document_type=None, **kwargs):
        document_type = document_type if document_type is not None else self.transcript
        return CourseDocumentRequirement.objects.create(
            course=course,
            document=document_type.code if document_type else f'legacy-{_sfx()}',
            document_type=document_type or None, **kwargs)

    def _upload(self, term=None, document_type=None, status=''):
        return StudentSupportingDocument.objects.create(
            term=term or self.fall, student=self.student,
            media=SimpleUploadedFile('doc.pdf', b'x'),
            document_type_ref=document_type or self.transcript, status=status)

    def _rows(self):
        return dr.requirements_for(self.student, terms=[self.fall])

    def _missing_labels(self):
        return [r.label for r in self._rows() if not r.satisfied]

    # -- requirement set ------------------------------------------------------

    def test_required_document_without_upload_is_missing(self):
        self._register(self.course_a)
        self._require(self.course_a)
        rows = self._rows()
        self.assertEqual([(r.label, r.satisfied) for r in rows], [('Transcript', False)])
        self.assertEqual(len(rows[0].courses), 1)
        self.assertIn('Alpha', rows[0].courses[0])

    def test_upload_in_the_term_satisfies_it(self):
        self._register(self.course_a)
        self._require(self.course_a)
        self._upload()
        self.assertEqual([r.satisfied for r in self._rows()], [True])

    def test_one_upload_covers_two_courses_as_one_row(self):
        self._register(self.course_a)
        self._register(self.course_b)
        self._require(self.course_a)
        self._require(self.course_b)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0].courses), 2)

    def test_not_required_inactive_and_other_grade_rows_are_ignored(self):
        self._register(self.course_a)
        self._require(self.course_a, required='2')
        self._require(self.course_a, document_type=self.shots, status='Inactive')
        self._register(self.course_b)
        self._require(self.course_b, document_type=self.shots, grade_levels=['9'])
        self.assertEqual(self._rows(), [])

    def test_grade_scoped_row_applies_to_that_grade(self):
        self._register(self.course_a)
        self._require(self.course_a, grade_levels=['11'])
        self.assertEqual(self._missing_labels(), ['Transcript'])

    def test_registration_status_outside_the_setting_is_ignored(self):
        self._enable(document_check_registration_statuses=['approved'])
        self._register(self.course_a, status='applied')
        self._require(self.course_a)
        self.assertEqual(self._rows(), [])

    def test_upload_in_an_unsatisfying_status_does_not_count(self):
        self._enable(satisfying_statuses=['Approved'])
        self._register(self.course_a)
        self._require(self.course_a)
        self._upload(status='Rejected')
        self.assertEqual(self._missing_labels(), ['Transcript'])

    def test_per_academic_year_upload_in_another_term_counts(self):
        self._register(self.course_a)
        self._require(self.course_a, recurrence='per_academic_year')
        self._upload(term=self.old)
        self.assertEqual([r.satisfied for r in self._rows()], [True])

    def test_unlinked_requirement_is_shown_as_missing(self):
        self._register(self.course_a)
        self._require(self.course_a, document_type=False)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].linked)
        self.assertFalse(rows[0].satisfied)

    def test_only_the_given_terms_are_checked(self):
        self._register(self.course_a, term=self.old)
        self._require(self.course_a)
        self.assertEqual(self._rows(), [])

    def test_missing_rows_sort_before_received(self):
        self._register(self.course_a)
        self._require(self.course_a)
        self._require(self.course_a, document_type=self.shots)
        self._upload()
        self.assertEqual([r.label for r in self._rows()],
                         ['Immunization Record', 'Transcript'])

    # -- the tab --------------------------------------------------------------

    def _tab(self):
        with mock.patch.object(dr, 'current_terms', return_value=[self.fall]):
            return dr.tab_context(self.student)

    def test_tab_is_unchanged_when_the_setting_is_off(self):
        self._settings(show_missing_documents='No')
        self._register(self.course_a)
        self._require(self.course_a)
        self.assertEqual(self._tab(), {})

    def test_setting_defaults_to_off(self):
        Setting.objects.filter(key=support_docs.key).delete()
        self.assertFalse(dr.is_enabled())

    def test_tab_is_unchanged_when_nothing_is_required(self):
        self._register(self.course_a)
        self.assertEqual(self._tab(), {})

    def test_panel_lists_missing_documents(self):
        self._register(self.course_a)
        self._require(self.course_a, description='Official copy only')
        html = render_to_string('cis/students/tabs/_missing_documents.html', self._tab())
        self.assertIn('Missing documents (1)', html)
        self.assertIn('Transcript', html)
        self.assertIn('Official copy only', html)

    def test_panel_says_all_received(self):
        self._register(self.course_a)
        self._require(self.course_a)
        self._upload()
        html = render_to_string('cis/students/tabs/_missing_documents.html', self._tab())
        self.assertIn('have been received', html)
        self.assertNotIn('Missing documents', html)
