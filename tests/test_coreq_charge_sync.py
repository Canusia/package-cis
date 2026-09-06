"""Charges must follow co-req (lecture + lab) registrations in both directions.

`cis.signals.registrations.update_registration` mirrors a registration's status
onto its co-req rows with a queryset `.update()` so the lecture->lab and
lab->lecture directions cannot recurse into each other. Raw SQL fires no
`post_save`, though, so `student_transactions.signals.manage_charges` never saw
the mirrored change and the lab's fee was left behind after the lecture was
dropped. `_mirror_status` re-sends `post_save` for each mirrored row.

`ClassSection.co_reqs` is `ManyToManyField('cis.ClassSection')`, not
`ManyToManyField('self')`, so it is not symmetrical: `lab.co_reqs` is empty and
the relation has to be walked backwards explicitly.

Skipped where `student_transactions` is not installed — the charge behaviour
being asserted lives in that package, not in `cis`.
"""
import importlib.util
import unittest
import uuid

from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models import CustomUser
from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.settings.registration_charges import registration_charges

HAS_STUDENT_TRANSACTIONS = importlib.util.find_spec('student_transactions') is not None

if HAS_STUDENT_TRANSACTIONS:
    from student_transactions.models import StudentTransaction


@unittest.skipUnless(
    HAS_STUDENT_TRANSACTIONS, 'student_transactions is not installed on this tenant')
class CoreqTestCase(TestCase):
    """A student registered in one lecture that lists one lab as a co-req."""

    def setUp(self):
        Group.objects.get_or_create(name='student')
        # Several registration signals call add_note, which falls back to the
        # 'cron' user when no request is bound (always true in tests).
        CustomUser.objects.create_user(
            username='cron', email='cron@example.com', password='x')

        Setting.objects.update_or_create(
            key=registration_charges.key,
            defaults={'value': {
                'is_active': 'Yes',
                'hs_pay_type': 'class_highschool',
                'charge_trigger': ['applied', 'registered'],
                'charge_remove_trigger': ['drop'],
            }},
        )

        ay = AcademicYear.objects.create(name='2026-2027')
        self.term = Term.objects.create(
            label='Fall 2026', code='26FA', academic_year=ay, dates={})
        self.highschool = HighSchool.objects.create(
            name='Test HS', code='THS', hs_pay_type='Student Pay')

        user = CustomUser.objects.create_user(
            username='stu', email='stu@example.com', password='x',
            first_name='Sam', last_name='Test')
        self.student = Student.objects.create(
            user=user, highschool=self.highschool, sis_id=uuid.uuid4())

        self.lecture = self._section('Lecture', 300.0)
        self.lab = self._section('Lab', 75.0)
        self.lecture.co_reqs.add(self.lab)

    def _section(self, label, cost):
        suffix = uuid.uuid4().hex[:6]
        cohort = Cohort.objects.create(name=f'Cohort {suffix}', designator=suffix[:3])
        course = Course.objects.create(
            catalog_number=suffix[:3], title=f'{label} {suffix}',
            name=f'C {suffix}', cohort=cohort)
        return ClassSection.objects.create(
            course=course, term=self.term, registration_term=self.term,
            highschool=self.highschool,
            class_number=f'C-{suffix}', section_number=suffix[:3],
            tuition=cost, lab_fees=0.0,
            external_sis_id=uuid.uuid4())

    def _reg(self, section):
        return StudentRegistration.objects.get(
            student=self.student, class_section=section)

    def _charges(self, section):
        return StudentTransaction.objects.filter(
            student=self.student,
            meta__registration=str(self._reg(section).id),
        )

    def _register_lecture(self):
        return StudentRegistration.objects.create(
            student=self.student, class_section=self.lecture,
            highschool=self.highschool, status='registered',
            pay_type='', non_student_pay_amount=0, status_changed_on={})


class CoreqChargeSyncTests(CoreqTestCase):
    """Status changes mirror onto co-req rows, and charges follow them."""

    def test_registering_the_lecture_charges_both_sections(self):
        self._register_lecture()

        self.assertEqual(self._charges(self.lecture).count(), 1)
        self.assertEqual(self._charges(self.lab).count(), 1)

    def test_dropping_the_lecture_removes_the_lab_charge(self):
        lecture_reg = self._register_lecture()

        lecture_reg.status = 'drop'
        lecture_reg.save()

        self.assertEqual(self._reg(self.lab).status, 'drop')
        self.assertEqual(self._charges(self.lecture).count(), 0)
        self.assertEqual(self._charges(self.lab).count(), 0)

    def test_dropping_the_lab_removes_the_lecture_charge(self):
        self._register_lecture()
        lab_reg = self._reg(self.lab)

        lab_reg.status = 'drop'
        lab_reg.save()

        self.assertEqual(self._reg(self.lecture).status, 'drop')
        self.assertEqual(self._charges(self.lecture).count(), 0)
        self.assertEqual(self._charges(self.lab).count(), 0)

    def test_dropping_the_lab_removes_a_sibling_labs_charge(self):
        lab_b = self._section('Lab B', 50.0)
        self.lecture.co_reqs.add(lab_b)
        self._register_lecture()

        lab_reg = self._reg(self.lab)
        lab_reg.status = 'drop'
        lab_reg.save()

        self.assertEqual(self._charges(self.lecture).count(), 0)
        self.assertEqual(self._charges(lab_b).count(), 0)

    def test_reinstating_the_lecture_recharges_the_lab(self):
        lecture_reg = self._register_lecture()
        lecture_reg.status = 'drop'
        lecture_reg.save()

        lecture_reg.status = 'registered'
        lecture_reg.save()

        self.assertEqual(self._charges(self.lecture).count(), 1)
        self.assertEqual(self._charges(self.lab).count(), 1)


class CoreqDeleteTests(CoreqTestCase):
    """Deleting either side of a co-req pair deletes the whole group.

    `remove_coreqs` used to walk `co_reqs` forwards only, so deleting the lab
    left the lecture registration and its tuition charge behind.
    """

    def _registrations(self):
        return StudentRegistration.objects.filter(student=self.student)

    def test_deleting_the_lecture_deletes_the_lab(self):
        lecture_reg = self._register_lecture()

        lecture_reg.delete()

        self.assertEqual(self._registrations().count(), 0)
        self.assertEqual(StudentTransaction.objects.filter(
            student=self.student).count(), 0)

    def test_deleting_the_lab_deletes_the_lecture(self):
        self._register_lecture()
        lab_reg = self._reg(self.lab)

        lab_reg.delete()

        self.assertEqual(self._registrations().count(), 0)
        self.assertEqual(StudentTransaction.objects.filter(
            student=self.student).count(), 0)

    def test_deleting_the_lab_deletes_a_sibling_lab(self):
        lab_b = self._section('Lab B', 50.0)
        self.lecture.co_reqs.add(lab_b)
        self._register_lecture()
        self.assertEqual(self._registrations().count(), 3)

        self._reg(self.lab).delete()

        self.assertEqual(self._registrations().count(), 0)
        self.assertEqual(StudentTransaction.objects.filter(
            student=self.student).count(), 0)

    def test_deleting_a_registration_without_coreqs_is_unaffected(self):
        standalone = self._section('Standalone', 120.0)
        reg = StudentRegistration.objects.create(
            student=self.student, class_section=standalone,
            highschool=self.highschool, status='registered',
            pay_type='', non_student_pay_amount=0, status_changed_on={})
        self._register_lecture()

        reg.delete()

        # the co-req pair is untouched
        self.assertEqual(self._registrations().count(), 2)
