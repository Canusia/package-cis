"""post_save receivers must not raise on an ordinary row (#69, #70, #71).

All three receivers here run on ``post_save``, so an exception escapes the
caller's ``save()`` *after* the row has been written -- the record exists and
the request 500s. Each was reachable without anything unusual: a note whose
meta has no 'type' key, a parent consent on a deployment where the
registration-email setting was never registered, and an administrator position
on one where init_groups has not run.

Found while building the query-count fixture for #67, which had to work around
all three to create one row of each model.
"""

import uuid

from django.conf import settings
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models import CustomUser
from cis.models.district import District
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition)
from cis.models.note import StudentNote
from cis.models.settings import Setting
from cis.models.student import ParentConsent, Student
from cis.models.term import AcademicYear, Term


def _short():
    return uuid.uuid4().hex[:8]


def _student():
    short = _short()
    Group.objects.get_or_create(name='student')
    user = CustomUser.objects.create_user(
        username=f'stu-{short}', email=f'stu-{short}@example.com',
        password='x', first_name='Avi', last_name='Codtest')
    return Student.objects.create(user=user, sis_id=uuid.uuid4())


def _term():
    short = _short()
    return Term.objects.create(
        label=f'Term-{short}', code=short,
        academic_year=AcademicYear.objects.create(name=f'AY-{short}'))


class StudentNoteMetaTypeTests(TestCase):
    """#69 -- `'to_parent' in instance.meta.get('type')` against None."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _student()
        cls.staff = CustomUser.objects.create_superuser(
            username='note-staff', email='note-staff@example.com',
            password='x')

    def test_a_note_whose_meta_has_no_type_key_saves(self):
        note = StudentNote.objects.create(
            student=self.student, createdby=self.staff, note='hello',
            meta={})
        self.assertTrue(
            StudentNote.objects.filter(pk=note.pk).exists())

    def test_a_note_with_no_meta_at_all_saves(self):
        note = StudentNote.objects.create(
            student=self.student, createdby=self.staff, note='hello',
            meta=None)
        self.assertTrue(
            StudentNote.objects.filter(pk=note.pk).exists())

    def test_a_note_with_an_unrelated_type_saves(self):
        note = StudentNote.objects.create(
            student=self.student, createdby=self.staff, note='hello',
            meta={'type': 'internal'})
        self.assertTrue(
            StudentNote.objects.filter(pk=note.pk).exists())

    def test_a_to_parent_note_still_notifies(self):
        """The guard must not cost the behaviour it guards."""
        from unittest import mock

        with mock.patch.object(StudentNote, 'send_to_parent') as send:
            StudentNote.objects.create(
                student=self.student, createdby=self.staff, note='hello',
                meta={'type': 'to_parent'})
        send.assert_called_once()

    def test_a_to_student_note_still_notifies(self):
        from unittest import mock

        with mock.patch.object(StudentNote, 'send_to_student') as send:
            StudentNote.objects.create(
                student=self.student, createdby=self.staff, note='hello',
                meta={'type': 'to_student'})
        send.assert_called_once()


class ParentConsentEmailSettingTests(TestCase):
    """#70 -- email_settings['parent_consent_recv'] on an empty settings dict."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _student()
        cls.term = _term()
        cls.key = getattr(settings, 'CAMPUS_CODE_PREFIX') + '_regis_email'

    def test_consent_saves_when_the_setting_is_unregistered(self):
        Setting.objects.filter(key=self.key).delete()
        consent = ParentConsent.objects.create(
            student=self.student, term=self.term, parent_signature='signed')
        self.assertTrue(
            ParentConsent.objects.filter(pk=consent.pk).exists())

    def test_consent_saves_when_notifications_are_off(self):
        Setting.objects.update_or_create(
            key=self.key, defaults={'value': {'is_active': 'No'}})
        consent = ParentConsent.objects.create(
            student=self.student, term=self.term, parent_signature='signed')
        self.assertTrue(
            ParentConsent.objects.filter(pk=consent.pk).exists())

    def test_no_mail_is_sent_when_notifications_are_off(self):
        from unittest import mock

        Setting.objects.update_or_create(
            key=self.key,
            defaults={'value': {'is_active': 'No',
                                'parent_consent_recv': 'hi'}})
        with mock.patch('cis.signals.students.send_html_mail') as send:
            ParentConsent.objects.create(
                student=self.student, term=self.term,
                parent_signature='signed')
        send.assert_not_called()

    def test_mail_is_still_sent_when_notifications_are_on(self):
        """The reordered guard must not stop the notification it guards."""
        from unittest import mock

        Setting.objects.update_or_create(
            key=self.key,
            defaults={'value': {
                'is_active': 'Yes',
                'parent_consent_recv': 'Consent received for {{ term }}.',
                'parent_consent_recv_subject': 'Consent received',
            }})
        with mock.patch('cis.signals.students.send_html_mail') as send:
            ParentConsent.objects.create(
                student=self.student, term=self.term,
                parent_signature='signed')
        send.assert_called_once()


class HSAdministratorPositionGroupTests(TestCase):
    """#71 -- Group.objects.get(name='highschool_admin') with no such group."""

    @classmethod
    def setUpTestData(cls):
        short = _short()
        user = CustomUser.objects.create_user(
            username=f'hsa-{short}', email=f'hsa-{short}@example.com',
            password='x')
        cls.hsadmin = HSAdministrator.objects.create(user=user)
        cls.highschool = HighSchool.objects.create(
            name=f'HS-{short}', code=short,
            district=District.objects.create(name=f'District-{short}'))
        cls.position = HSPosition.objects.create(name=f'Counselor-{short}')

    def test_position_saves_without_the_group_present(self):
        Group.objects.filter(name='highschool_admin').delete()
        record = HSAdministratorPosition.objects.create(
            hsadmin=self.hsadmin, highschool=self.highschool,
            position=self.position, status='Active')
        self.assertTrue(
            HSAdministratorPosition.objects.filter(pk=record.pk).exists())

    def test_an_active_position_still_grants_the_group(self):
        """The guard must not cost the behaviour it guards: the receiver's job
        is to keep the user's highschool_admin membership in step."""
        Group.objects.filter(name='highschool_admin').delete()
        HSAdministratorPosition.objects.create(
            hsadmin=self.hsadmin, highschool=self.highschool,
            position=self.position, status='Active')
        self.assertTrue(
            self.hsadmin.user.groups.filter(
                name='highschool_admin').exists())


class TeacherNoteMetaTypeTests(TestCase):
    """#69 again, one receiver down: teacher_note_added has the same
    `'to_instructor' in instance.meta.get('type')` in the same module."""

    @classmethod
    def setUpTestData(cls):
        from cis.models.teacher import Teacher

        short = _short()
        Group.objects.get_or_create(name='instructor')
        user = CustomUser.objects.create_user(
            username=f'tch-{short}', email=f'tch-{short}@example.com',
            password='x', first_name='Tess', last_name='Teacher')
        cls.teacher = Teacher.objects.create(user=user)
        cls.staff = CustomUser.objects.create_superuser(
            username=f'tn-staff-{short}',
            email=f'tn-staff-{short}@example.com', password='x')

    def test_a_note_whose_meta_has_no_type_key_saves(self):
        from cis.models.note import TeacherNote

        note = TeacherNote.objects.create(
            teacher=self.teacher, createdby=self.staff, note='hello', meta={})
        self.assertTrue(TeacherNote.objects.filter(pk=note.pk).exists())

    def test_a_to_instructor_note_still_emails(self):
        from unittest import mock

        from cis.models.note import TeacherNote

        with mock.patch.object(TeacherNote, 'send_as_email') as send:
            TeacherNote.objects.create(
                teacher=self.teacher, createdby=self.staff, note='hello',
                meta={'type': 'to_instructor'})
        send.assert_called_once()
