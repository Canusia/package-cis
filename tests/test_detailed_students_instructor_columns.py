"""Instructor and grade-status columns on detailed_students_with_class.

Ported from FLCC (ewu#59 item 2). These columns are addressed by dotted path
strings resolved through `get_field`, which swallows AttributeError and returns
''. That is the right behaviour for a section with no teacher, but it also
means a MISTYPED path exports a column of empty strings instead of failing —
so the paths themselves are what these tests pin.
"""
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.customuser import CustomUser
from cis.models.course import Course, Cohort
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term
from cis.utils import get_field

INSTRUCTOR_FIRST = 'class_section.teacher.user.first_name'
INSTRUCTOR_LAST = 'class_section.teacher.user.last_name'
GRADE_STATUS = 'class_section.grade_status'


class InstructorColumnPathTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@localhost'})
        self.ay = AcademicYear.objects.create(name='2025-2026')
        self.term = Term.objects.create(
            label='Fall 2025', code='FA25', academic_year=self.ay)
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        self.cohort = Cohort.objects.create(name='English', designator='ENGL')
        self.course = Course.objects.create(
            name='ENGL& 101', title='Comp I', catalog_number='101',
            cohort=self.cohort, status='Active')

    def _registration(self, teacher=None, grade_status=''):
        section = ClassSection.objects.create(
            course=self.course, term=self.term, highschool=self.hs,
            registration_term=self.term, teacher=teacher,
            grade_status=grade_status,
            class_number=f'C{ClassSection.objects.count():05d}',
            section_number='01')
        user = CustomUser.objects.create(username='stu1', email='stu1@x.com')
        student = Student.objects.create(
            user=user, highschool=self.hs, grade_level='JR')
        return StudentRegistration.objects.create(
            student=student, class_section=section, highschool=self.hs,
            status='registered', status_changed_on={})

    def test_instructor_name_paths_resolve(self):
        teacher = Teacher.objects.create(
            user=CustomUser.objects.create(
                username='t1', email='t1@x.com',
                first_name='Ada', last_name='Lovelace'))
        record = self._registration(teacher=teacher)

        self.assertEqual(get_field(record, INSTRUCTOR_FIRST), 'Ada')
        self.assertEqual(get_field(record, INSTRUCTOR_LAST), 'Lovelace')

    def test_grade_status_path_resolves(self):
        record = self._registration(grade_status='submitted')

        self.assertEqual(get_field(record, GRADE_STATUS), 'submitted')

    def test_section_without_a_teacher_exports_blank_not_error(self):
        record = self._registration(teacher=None)

        self.assertEqual(get_field(record, INSTRUCTOR_FIRST), '')
        self.assertEqual(get_field(record, INSTRUCTOR_LAST), '')


class ReportColumnRegistrationTests(TestCase):
    """The columns must actually be wired into the export's header."""

    def test_report_declares_the_new_columns(self):
        import inspect
        from cis.reports import detailed_students_with_class as report

        source = inspect.getsource(report)

        self.assertIn("'Instructor First Name'", source)
        self.assertIn("'Instructor Last Name'", source)
        self.assertIn("'Class Grade Status'", source)

    def test_teacher_relation_is_prefetched(self):
        """Without this the two instructor columns cost two queries per row."""
        import inspect
        from cis.reports import detailed_students_with_class as report

        source = inspect.getsource(report)

        self.assertIn("'class_section__teacher__user'", source)
