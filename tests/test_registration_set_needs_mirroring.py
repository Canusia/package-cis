"""Bulk 'Set Needs Mirroring' action on /ce/registrations/.

Covers SetNeedsMirroringForm.save(): it sets needs_mirroring to the chosen
Yes/No value on exactly the selected registrations, leaving others untouched.
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
from cis.forms.section import SetNeedsMirroringForm


def _post_data(ids, value):
    qd = QueryDict(mutable=True)
    qd['action'] = 'set_needs_mirroring'
    qd['needs_mirroring'] = value
    qd.setlist('registration_ids', [str(i) for i in ids])
    return qd


class SetNeedsMirroringFormTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        # The StudentRegistration post_save signal falls back to the 'cron' user.
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
        for i in range(3):
            user = CustomUser.objects.create_user(
                username=f'stu{i}', email=f'stu{i}@example.com', password='x',
                first_name=f'S{i}', last_name='Test')
            student = Student.objects.create(user=user, sis_id=uuid.uuid4())
            self.regs.append(StudentRegistration.objects.create(
                student=student, class_section=self.section,
                status='applied', status_changed_on={}))

    def test_sets_flag_true_on_selected_only(self):
        r1, r2, r3 = self.regs
        form = SetNeedsMirroringForm(data=_post_data([r1.id, r2.id], '1'))
        self.assertTrue(form.is_valid(), form.errors.as_json())
        form.save()
        r1.refresh_from_db(); r2.refresh_from_db(); r3.refresh_from_db()
        self.assertTrue(r1.needs_mirroring)
        self.assertTrue(r2.needs_mirroring)
        # untouched control registration keeps its original (unset) value
        self.assertFalse(bool(r3.needs_mirroring))

    def test_sets_flag_false(self):
        r1 = self.regs[0]
        r1.needs_mirroring = True
        r1.save()
        form = SetNeedsMirroringForm(data=_post_data([r1.id], '0'))
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertFalse(form.save())
        r1.refresh_from_db()
        self.assertFalse(r1.needs_mirroring)

    def test_save_only_updates_allowed_ids(self):
        # IDOR guard: even if a caller submits ids outside their authorized
        # (campus-scoped) set, save() mutates only the allowed intersection.
        r1, r2 = self.regs[0], self.regs[1]
        form = SetNeedsMirroringForm(data=_post_data([r1.id, r2.id], '1'))
        self.assertTrue(form.is_valid(), form.errors.as_json())
        form.save(allowed_ids=[r1.id])   # r2 not authorized
        r1.refresh_from_db(); r2.refresh_from_db()
        self.assertTrue(r1.needs_mirroring)
        self.assertFalse(bool(r2.needs_mirroring))

    def test_value_is_required(self):
        r1 = self.regs[0]
        data = _post_data([r1.id], '')
        del data['needs_mirroring']
        form = SetNeedsMirroringForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('needs_mirroring', form.errors)
