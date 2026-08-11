"""Faculty -> teacher assignment: the model, the rule, and the tenant seam.

Spec: docs/superpowers/specs/2026-08-11-faculty-teacher-assignment-design.md

Today a faculty member sees every teacher holding a TeacherCourseCertificate
for any course they administer (cis/views/teacher.py:227). `visible_teachers`
narrows that per (faculty, course, academic_year) when assignment rows exist,
and reproduces today's list exactly when they do not -- so the feature ships
dark and can be enabled one course at a time.

EWU has no test factories, so fixtures are built with direct
Model.objects.create(), following cis/tests/test_class_section_course_administrator_filter.py.
"""
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.faculty import FacultyTeacherAssignment
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherCourseCertificate, TeacherHighSchool
from cis.models.term import AcademicYear
from cis.services import faculty_scope

User = get_user_model()

FAKE_TENANT = 'cis.tests.fake_tenant'


def _suffix():
    return uuid.uuid4().hex[:8]


def _user():
    sfx = _suffix()
    return User.objects.create_user(
        username=f'u_{sfx}', email=f'u_{sfx}@example.com', password='x')


class FacultyScopeFixtureMixin:
    def setUp(self):
        Group.objects.get_or_create(name='instructor')
        self.cohort = Cohort.objects.create(name=f'Co-{_suffix()}', designator='CO')
        self.hs = HighSchool.objects.create(name=f'HS-{_suffix()}')
        self.year = AcademicYear.objects.create(name=f'AY-{_suffix()}')
        self.other_year = AcademicYear.objects.create(name=f'AY-{_suffix()}')
        self.faculty = _user()

    def _course(self, title='C'):
        return Course.objects.create(
            catalog_number='101', title=f'{title}-{_suffix()}', cohort=self.cohort)

    def _teacher(self):
        return Teacher.objects.create(user=_user(), status='active')

    def _oversees(self, course, user=None, status='Active'):
        return CourseAdministrator.objects.create(
            course=course, user=user or self.faculty, status=status)

    def _certifies(self, teacher, course):
        ths, _ = TeacherHighSchool.objects.get_or_create(
            teacher=teacher, highschool=self.hs)
        return TeacherCourseCertificate.objects.create(
            teacher_highschool=ths, course=course)

    def _assign(self, teacher, course, year=None, user=None):
        return FacultyTeacherAssignment.objects.create(
            user=user or self.faculty, course=course, teacher=teacher,
            academic_year=year or self.year)


class FacultyTeacherAssignmentModelTests(FacultyScopeFixtureMixin, TestCase):
    """Task 1 -- the model itself."""

    def test_duplicate_assignment_is_rejected(self):
        course, teacher = self._course(), self._teacher()
        self._assign(teacher, course)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._assign(teacher, course)

    def test_same_teacher_may_be_assigned_for_a_different_year(self):
        course, teacher = self._course(), self._teacher()
        self._assign(teacher, course)
        self._assign(teacher, course, year=self.other_year)

        self.assertEqual(FacultyTeacherAssignment.objects.count(), 2)

    def test_created_by_may_be_null(self):
        row = self._assign(self._teacher(), self._course())

        self.assertIsNone(row.created_by)
        self.assertIsNotNone(row.created_on)

    def test_deleting_the_course_removes_the_assignment(self):
        """CASCADE, not PROTECT: an assignment is configuration, and a stale
        row must never be what blocks deleting a course."""
        course, teacher = self._course(), self._teacher()
        self._assign(teacher, course)

        course.delete()

        self.assertEqual(FacultyTeacherAssignment.objects.count(), 0)

    def test_deleting_the_teacher_removes_the_assignment(self):
        course, teacher = self._course(), self._teacher()
        self._assign(teacher, course)

        teacher.delete()

        self.assertEqual(FacultyTeacherAssignment.objects.count(), 0)


class VisibleTeachersTests(FacultyScopeFixtureMixin, TestCase):
    """Task 2 -- the rule."""

    def test_assigned_course_returns_only_the_assigned_teachers(self):
        course = self._course()
        self._oversees(course)
        mine, theirs = self._teacher(), self._teacher()
        self._certifies(mine, course)
        self._certifies(theirs, course)
        self._assign(mine, course)

        result = faculty_scope.visible_teachers(self.faculty, academic_year=self.year)

        self.assertEqual(set(result), {mine})

    def test_unassigned_course_returns_the_full_certificate_list(self):
        course = self._course()
        self._oversees(course)
        a, b = self._teacher(), self._teacher()
        self._certifies(a, course)
        self._certifies(b, course)

        result = faculty_scope.visible_teachers(self.faculty, academic_year=self.year)

        self.assertEqual(set(result), {a, b})

    def test_one_assigned_and_one_unassigned_course_in_a_single_call(self):
        assigned_course, open_course = self._course('A'), self._course('B')
        self._oversees(assigned_course)
        self._oversees(open_course)
        picked, skipped = self._teacher(), self._teacher()
        self._certifies(picked, assigned_course)
        self._certifies(skipped, assigned_course)
        self._assign(picked, assigned_course)
        open_a, open_b = self._teacher(), self._teacher()
        self._certifies(open_a, open_course)
        self._certifies(open_b, open_course)

        result = faculty_scope.visible_teachers(self.faculty, academic_year=self.year)

        self.assertEqual(set(result), {picked, open_a, open_b})

    def test_assignments_in_another_year_do_not_narrow_this_year(self):
        course = self._course()
        self._oversees(course)
        a, b = self._teacher(), self._teacher()
        self._certifies(a, course)
        self._certifies(b, course)
        self._assign(a, course, year=self.other_year)

        result = faculty_scope.visible_teachers(self.faculty, academic_year=self.year)

        self.assertEqual(set(result), {a, b})

    def test_another_facultys_assignments_do_not_narrow_this_faculty(self):
        course = self._course()
        self._oversees(course)
        other_faculty = _user()
        self._oversees(course, user=other_faculty)
        a, b = self._teacher(), self._teacher()
        self._certifies(a, course)
        self._certifies(b, course)
        self._assign(a, course, user=other_faculty)

        result = faculty_scope.visible_teachers(self.faculty, academic_year=self.year)

        self.assertEqual(set(result), {a, b})

    def test_inactive_oversight_row_is_ignored(self):
        course = self._course()
        self._oversees(course, status='Inactive')
        self._certifies(self._teacher(), course)

        result = faculty_scope.visible_teachers(self.faculty, academic_year=self.year)

        self.assertEqual(list(result), [])

    def test_a_faculty_overseeing_nothing_sees_nobody(self):
        stray_course = self._course()
        self._certifies(self._teacher(), stray_course)

        result = faculty_scope.visible_teachers(self.faculty, academic_year=self.year)

        self.assertEqual(list(result), [])

    def test_academic_year_defaults_to_the_active_year(self):
        course = self._course()
        self._oversees(course)
        assigned, other = self._teacher(), self._teacher()
        self._certifies(assigned, course)
        self._certifies(other, course)
        self._assign(assigned, course, year=self.year)

        with mock.patch.object(
                faculty_scope, 'active_academic_year', return_value=self.year) as m:
            result = set(faculty_scope.visible_teachers(self.faculty))

        m.assert_called_once_with()
        self.assertEqual(result, {assigned})

    def _build_courses(self, count):
        faculty = _user()
        for i in range(count):
            course = self._course(f'N{i}')
            CourseAdministrator.objects.create(
                course=course, user=faculty, status='Active')
            teacher = self._teacher()
            self._certifies(teacher, course)
            if i % 2 == 0:
                FacultyTeacherAssignment.objects.create(
                    user=faculty, course=course, teacher=teacher,
                    academic_year=self.year)
        return faculty

    def test_query_count_is_constant_in_the_number_of_overseen_courses(self):
        """Two subqueries and a union -- never a loop over courses.

        A per-course implementation grows linearly here; this is the assertion
        that forbids it.
        """
        one = self._build_courses(1)
        five = self._build_courses(5)

        with self.assertNumQueries(1):
            list(faculty_scope.visible_teachers(one, academic_year=self.year))

        with self.assertNumQueries(1):
            list(faculty_scope.visible_teachers(five, academic_year=self.year))


class VisibleTeachersTenantSeamTests(FacultyScopeFixtureMixin, TestCase):
    """Task 3 -- the tenant seam."""

    def test_without_a_tenant_module_the_cis_default_runs(self):
        course = self._course()
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)

        result = faculty_scope.visible_teachers(self.faculty, academic_year=self.year)

        self.assertEqual(set(result), {teacher})

    @override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
    def test_a_tenant_override_replaces_the_default_and_gets_the_arguments(self):
        sentinel = object()
        override = mock.Mock(return_value=sentinel)
        module = mock.Mock(visible_teachers=override)

        with mock.patch(
                'cis.services.tenant_services.importlib.import_module',
                return_value=module):
            result = faculty_scope.visible_teachers(
                self.faculty, academic_year=self.year)

        self.assertIs(result, sentinel)
        override.assert_called_once_with(self.faculty, academic_year=self.year)

    @override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
    def test_a_tenant_module_that_fails_to_import_propagates(self):
        boom = ImportError('no module named nonexistent_thing')
        boom.name = 'nonexistent_thing'

        with mock.patch(
                'cis.services.tenant_services.importlib.import_module',
                side_effect=boom):
            with self.assertRaises(ImportError):
                faculty_scope.visible_teachers(
                    self.faculty, academic_year=self.year)

    @override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
    def test_a_tenant_that_re_exports_the_wrapper_does_not_recurse(self):
        """ewu's tenant module is a thin re-export. If it re-exports the
        public entrypoint rather than `default_visible_teachers`, the seam
        must still terminate instead of recursing forever."""
        course = self._course()
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)
        module = mock.Mock(visible_teachers=faculty_scope.visible_teachers)

        with mock.patch(
                'cis.services.tenant_services.importlib.import_module',
                return_value=module):
            result = faculty_scope.visible_teachers(
                self.faculty, academic_year=self.year)

        self.assertEqual(set(result), {teacher})

    def test_default_is_reachable_under_its_own_name(self):
        """Tenant modules re-export `default_visible_teachers`; it must exist
        and behave as the rule."""
        course = self._course()
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)

        result = faculty_scope.default_visible_teachers(
            self.faculty, academic_year=self.year)

        self.assertEqual(set(result), {teacher})
