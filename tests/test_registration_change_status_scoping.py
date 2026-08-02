"""IDOR guard for the change_status bulk action.

StudentRegistrationChangeStatusForm builds its registration_ids choices from
the submitted POST data, so it validates any id. save(allowed_ids=...) must
mutate only the caller's campus-authorized intersection (the view supplies it
via processable_ids on POST).
"""
import uuid

from django.contrib.auth.models import Group
from django.http import QueryDict
from django.test import TestCase

from cis.models import CustomUser
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.course import Course, Cohort
from cis.models.term import Term, AcademicYear
from cis.forms.section import StudentRegistrationChangeStatusForm


class ChangeStatusScopingTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.create_user(
            username='cron', email='cron@example.com', password='x')
        cohort = Cohort.objects.create(name='Astronomy', designator='A')
        course = Course.objects.create(
            catalog_number='001', title='Descriptive Astronomy',
            name='A 001', cohort=cohort)
        ay = AcademicYear.objects.create(name='2026-2027')
        term = Term.objects.create(label='Fall 2026', code='26FA', academic_year=ay)
        self.section = ClassSection.objects.create(
            course=course, term=term,
            class_number='A-001-3428', section_number='3428',
            external_sis_id=uuid.uuid4())
        self.regs = []
        for i in range(2):
            user = CustomUser.objects.create_user(
                username=f'stu{i}', email=f'stu{i}@example.com', password='x',
                first_name=f'S{i}', last_name='Test')
            student = Student.objects.create(user=user, sis_id=uuid.uuid4())
            self.regs.append(StudentRegistration.objects.create(
                student=student, class_section=self.section,
                status='applied', status_changed_on={}))

    def _data(self, ids, new_status='approved'):
        qd = QueryDict(mutable=True)
        qd['action'] = 'change_status'
        qd['new_status'] = new_status
        qd.setlist('registration_ids', [str(i) for i in ids])
        return qd

    def test_save_only_updates_allowed_ids(self):
        r1, r2 = self.regs
        form = StudentRegistrationChangeStatusForm(data=self._data([r1.id, r2.id]))
        self.assertTrue(form.is_valid(), form.errors.as_json())
        form.save(allowed_ids=[r1.id])   # r2 not authorized
        r1.refresh_from_db(); r2.refresh_from_db()
        self.assertEqual(r1.status, 'approved')
        self.assertEqual(r2.status, 'applied')   # unauthorized id left untouched
