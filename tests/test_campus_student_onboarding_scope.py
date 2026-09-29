"""MC-13 (#37): staff see applicants who haven't picked classes yet.

A verified student with no registration is tied to a campus by their
onboarding term's academic year, so CE staff of that campus -- and only that
campus -- can see and act on them.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.campus_gate import (
    can_access_student, processable_student_ids, scope_records_by_student_campus,
    scope_students_by_campus,
)
from cis.models.course import Campus
from cis.models.customuser import CustomUser
from cis.models.note import StudentNote
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from student_onboarding.models import StudentOnboarding


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


class OnboardingCampusScopeTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')
        year = AcademicYear.objects.create(name=f'AY-{uuid.uuid4().hex[:6]}', campus=self.c1)
        term = Term.objects.create(academic_year=year, code='C1-FA', label='C1-FA')
        user = CustomUser.objects.create_user(
            username=f's{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        self.applicant = Student.objects.create(user=user, account_verified=True)
        StudentOnboarding.objects.get_or_create(student=self.applicant, term=term)

        self.staff_c1 = self._ce(self.c1)
        self.staff_c2 = self._ce(self.c2)

    def _ce(self, campus):
        user = CustomUser.objects.create_user(
            username=f'ce{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        user.groups.add(Group.objects.get_or_create(name='ce')[0])
        user.campus = {'process_campus': [str(campus.id)]}
        user.save()
        return user

    def test_scope_includes_the_applicant_for_their_campus_only(self):
        students = Student.objects.filter(pk=self.applicant.pk)
        self.assertTrue(scope_students_by_campus(students, self.staff_c1).exists())
        self.assertFalse(scope_students_by_campus(students, self.staff_c2).exists())

    def test_object_check(self):
        self.assertTrue(can_access_student(self.staff_c1, self.applicant))
        self.assertFalse(can_access_student(self.staff_c2, self.applicant))

    def test_bulk_action_ids(self):
        ids = [str(self.applicant.pk)]
        self.assertEqual(processable_student_ids(ids, self.staff_c1), ids)
        self.assertEqual(processable_student_ids(ids, self.staff_c2), [])

    def test_student_backed_records(self):
        StudentNote.objects.create(student=self.applicant, note='hi', createdby=self.staff_c1)
        notes = StudentNote.objects.filter(student=self.applicant)
        self.assertTrue(scope_records_by_student_campus(notes, self.staff_c1).exists())
        self.assertFalse(scope_records_by_student_campus(notes, self.staff_c2).exists())
