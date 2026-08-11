"""CE faculty-detail "Assigned Instructor(s)" tab (plan tasks 6 and 8).

Spec: docs/superpowers/specs/2026-08-11-faculty-teacher-assignment-design.md

The tab is the only place CE configures `FacultyTeacherAssignment`, so these
tests pin the two things a reader of the page depends on:

- a course with nothing picked says **"All instructors (unassigned)"** in words.
  The fallback is a state the page states, never one inferred from an empty box.
- what the picker offers, and what saving writes, is derived from exactly the
  same `CourseAdministrator(status__iexact='active')` + `TeacherCourseCertificate`
  chain as `cis/services/faculty_scope.py`, so the admin screen and the
  enforcement rule can never disagree.

EWU has no test factories; fixtures use direct Model.objects.create(), and the
django_login_history post_login receiver is disconnected for the duration of
each case (see cis/tests/test_faculty_coordinator_tabs.py).
"""
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.faculty import FacultyCoordinator, FacultyTeacherAssignment
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherCourseCertificate, TeacherHighSchool
from cis.models.term import AcademicYear
from cis.tabs import faculty_coordinator as fc_tabs

User = get_user_model()

UNASSIGNED_TEXT = 'All instructors (unassigned)'


def _suffix():
    return uuid.uuid4().hex[:8]


def _user():
    sfx = _suffix()
    return User.objects.create_user(
        username=f'u_{sfx}', email=f'u_{sfx}@example.com', password='x',
        first_name='T', last_name=f'Last{sfx}')


class AssignedInstructorsTabMixin:
    def setUp(self):
        self._saved_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []

        Group.objects.get_or_create(name='faculty')
        Group.objects.get_or_create(name='instructor')
        ce_group, _ = Group.objects.get_or_create(name='ce')

        sfx = _suffix()
        self.ce_user = User.objects.create_superuser(
            username=f'ce_{sfx}', email=f'ce_{sfx}@example.com', password='x')
        self.ce_user.groups.add(ce_group)
        self.client.force_login(self.ce_user)

        self.record = FacultyCoordinator.objects.create(user=_user())
        self.faculty = self.record.user

        self.cohort = Cohort.objects.create(name=f'Co-{_suffix()}', designator='CO')
        self.hs = HighSchool.objects.create(name=f'HS-{_suffix()}')
        self.year = AcademicYear.objects.create(name=f'AY-{_suffix()}')
        self.other_year = AcademicYear.objects.create(name=f'AY-{_suffix()}')

    def tearDown(self):
        user_logged_in.receivers = self._saved_receivers

    # --- fixtures -------------------------------------------------------
    def _course(self, title='C'):
        return Course.objects.create(
            catalog_number='101', title=f'{title}-{_suffix()}', cohort=self.cohort)

    def _teacher(self):
        return Teacher.objects.create(user=_user(), status='active')

    def _oversees(self, course, status='Active'):
        return CourseAdministrator.objects.create(
            course=course, user=self.faculty, status=status)

    def _certifies(self, teacher, course):
        ths, _ = TeacherHighSchool.objects.get_or_create(
            teacher=teacher, highschool=self.hs)
        return TeacherCourseCertificate.objects.create(
            teacher_highschool=ths, course=course)

    def _assign(self, teacher, course, year=None, user=None):
        return FacultyTeacherAssignment.objects.create(
            user=user or self.faculty, course=course, teacher=teacher,
            academic_year=year or self.year)

    # --- transport ------------------------------------------------------
    @property
    def _url(self):
        return reverse('cis:faculty_coordinator_tab',
                       kwargs={'record_id': self.record.pk,
                               'tab_slug': 'assigned_instructors'})

    def _get(self, **params):
        with mock.patch.object(fc_tabs, 'active_academic_year',
                               return_value=self.year):
            resp = self.client.get(self._url, params)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def _post(self, data):
        with mock.patch.object(fc_tabs, 'active_academic_year',
                               return_value=self.year):
            resp = self.client.post(self._url, data)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def _rows(self, year=None):
        return set(FacultyTeacherAssignment.objects.filter(
            user=self.faculty, academic_year=year or self.year
        ).values_list('course_id', 'teacher_id'))


class AssignedInstructorsRegistrationTests(AssignedInstructorsTabMixin, TestCase):
    def test_tab_is_registered_between_courses_and_class_sections(self):
        from myce.component_registry.faculty_coordinator import faculty_coordinator_tabs
        meta = faculty_coordinator_tabs._tabs['assigned_instructors']
        self.assertEqual(meta['title'], 'Assigned Instructor(s)')
        self.assertEqual(meta['order'], 15)
        self.assertGreater(meta['order'],
                           faculty_coordinator_tabs._tabs['courses']['order'])
        self.assertLess(meta['order'],
                        faculty_coordinator_tabs._tabs['class_sections']['order'])
        self.assertTrue(meta['lazy'])
        self.assertFalse(meta['active'])

    def test_detail_page_shows_the_tab_anchor(self):
        resp = self.client.get(reverse('cis:faculty_coordinator',
                                       kwargs={'record_id': self.record.pk}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('href="#assigned_instructors"', html)
        self.assertIn('Assigned Instructor(s)', html)

    def test_fragment_is_a_bare_partial_in_the_card_wrapper(self):
        html = self._get()
        self.assertNotIn('tab-pane', html)
        self.assertNotIn('<html', html)
        self.assertIn('card border-top-0', html)
        self.assertIn('card-body', html)


class AssignedInstructorsRenderTests(AssignedInstructorsTabMixin, TestCase):
    def test_unassigned_course_says_all_instructors_unassigned(self):
        course = self._course('Bare')
        self._oversees(course)
        self._certifies(self._teacher(), course)

        html = self._get()
        self.assertIn(course.title, html)
        self.assertIn(UNASSIGNED_TEXT, html)

    def test_assigned_course_does_not_claim_to_be_unassigned(self):
        course = self._course('Set')
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)
        self._assign(teacher, course)

        html = self._get()
        self.assertNotIn(UNASSIGNED_TEXT, html)
        self.assertIn(str(teacher), html)

    def test_only_actively_overseen_courses_are_listed(self):
        active = self._course('Active')
        self._oversees(active)
        inactive = self._course('Inactive')
        self._oversees(inactive, status='Inactive')

        html = self._get()
        self.assertIn(active.title, html)
        self.assertNotIn(inactive.title, html)

    def test_picker_offers_only_teachers_certified_for_that_course(self):
        course = self._course('Mine')
        self._oversees(course)
        certified = self._teacher()
        self._certifies(certified, course)

        other_course = self._course('Other')
        self._oversees(other_course)
        elsewhere = self._teacher()
        self._certifies(elsewhere, other_course)

        html = self._get()
        options = html.split(f'name="teachers_{course.id}"')[1].split('</select>')[0]
        self.assertIn(str(certified.id), options)
        self.assertNotIn(str(elsewhere.id), options)

    def test_faculty_overseeing_nothing_gets_an_empty_state(self):
        # No picker at all -- and no bare "All instructors (unassigned)" either,
        # which would read as a claim about courses that do not exist.
        html = self._get()
        self.assertNotIn('name="teachers_', html)
        self.assertNotIn(UNASSIGNED_TEXT, html)
        self.assertIn('does not actively oversee any courses', html)

    def test_year_selector_defaults_to_the_active_academic_year(self):
        html = self._get()
        self.assertIn(f'value="{self.year.id}" selected', html)

    def test_the_active_year_is_labelled_in_the_selector(self):
        """QA read a year named "2026 - 2027 - DELETE ME" as junk, switched to a
        similarly-named inactive year, and configured assignments that the
        portal then ignored. The active year must identify itself, since its
        name cannot be relied on to."""
        html = self._get()
        self.assertIn(f'{self.year} (active)', html)
        self.assertNotIn(f'{self.other_year} (active)', html)

    def test_editing_an_inactive_year_says_the_saves_are_inert(self):
        """The wrong-year no-op is invisible without this: the fallback
        over-shows, so a misconfigured year and an unconfigured one produce the
        same full list."""
        html = self._get(academic_year=str(self.other_year.id))
        self.assertIn('is not the active academic year', html)
        self.assertIn(str(self.year), html)

    def test_no_warning_on_the_active_year(self):
        self.assertNotIn('is not the active academic year', self._get())

    def test_year_parameter_scopes_what_is_shown(self):
        course = self._course('Yearly')
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)
        self._assign(teacher, course, year=self.year)

        this_year = self._get(academic_year=str(self.year.id))
        self.assertNotIn(UNASSIGNED_TEXT, this_year)

        next_year = self._get(academic_year=str(self.other_year.id))
        self.assertIn(UNASSIGNED_TEXT, next_year)
        self.assertIn(f'value="{self.other_year.id}" selected', next_year)


class AssignedInstructorsSaveTests(AssignedInstructorsTabMixin, TestCase):
    def _save(self, courses, selections, year=None):
        data = {
            'action': 'save_assigned_instructors',
            'academic_year': str((year or self.year).id),
            'course': [str(c.id) for c in courses],
        }
        for course, teachers in selections.items():
            data[f'teachers_{course.id}'] = [str(t.id) for t in teachers]
        return self._post(data)

    def test_saving_a_selection_creates_exactly_those_rows(self):
        course = self._course('Save')
        self._oversees(course)
        keep, drop = self._teacher(), self._teacher()
        self._certifies(keep, course)
        self._certifies(drop, course)

        self._save([course], {course: [keep]})

        self.assertEqual(self._rows(), {(course.id, keep.id)})

    def test_created_by_is_the_acting_user(self):
        course = self._course('Stamp')
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)

        self._save([course], {course: [teacher]})

        row = FacultyTeacherAssignment.objects.get(user=self.faculty)
        self.assertEqual(row.created_by, self.ce_user)

    def test_clearing_a_selection_deletes_the_rows_and_restores_the_fallback(self):
        course = self._course('Clear')
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)
        self._assign(teacher, course)

        html = self._save([course], {})

        self.assertEqual(self._rows(), set())
        self.assertIn(UNASSIGNED_TEXT, html)

    def test_a_course_absent_from_the_post_is_left_alone(self):
        # A browser omits an empty multi-select entirely, so "cleared" and
        # "never rendered" are only distinguishable by the hidden course list.
        touched, untouched = self._course('Touched'), self._course('Untouched')
        self._oversees(touched)
        self._oversees(untouched)
        teacher = self._teacher()
        self._certifies(teacher, touched)
        self._certifies(teacher, untouched)
        self._assign(teacher, untouched)

        self._save([touched], {touched: [teacher]})

        self.assertEqual(self._rows(),
                         {(touched.id, teacher.id), (untouched.id, teacher.id)})

    def test_saving_does_not_touch_another_year(self):
        course = self._course('Isolated')
        self._oversees(course)
        a, b = self._teacher(), self._teacher()
        self._certifies(a, course)
        self._certifies(b, course)
        self._assign(a, course, year=self.other_year)

        self._save([course], {course: [b]})

        self.assertEqual(self._rows(), {(course.id, b.id)})
        self.assertEqual(self._rows(self.other_year), {(course.id, a.id)})

    def test_saving_does_not_touch_another_faculty_member(self):
        course = self._course('Shared')
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)
        other_faculty = _user()
        CourseAdministrator.objects.create(
            course=course, user=other_faculty, status='Active')
        self._assign(teacher, course, user=other_faculty)

        self._save([course], {})

        self.assertTrue(FacultyTeacherAssignment.objects.filter(
            user=other_faculty, course=course).exists())

    def test_a_course_not_actively_overseen_cannot_be_assigned(self):
        course = self._course('Foreign')
        teacher = self._teacher()
        self._certifies(teacher, course)

        self._save([course], {course: [teacher]})

        self.assertEqual(self._rows(), set())

    def test_a_teacher_not_certified_for_the_course_cannot_be_assigned(self):
        course = self._course('Uncertified')
        self._oversees(course)
        stranger = self._teacher()

        self._save([course], {course: [stranger]})

        self.assertEqual(self._rows(), set())

    def test_saving_is_idempotent(self):
        course = self._course('Twice')
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)

        self._save([course], {course: [teacher]})
        first = FacultyTeacherAssignment.objects.get(user=self.faculty)
        self._save([course], {course: [teacher]})

        self.assertEqual(self._rows(), {(course.id, teacher.id)})
        self.assertEqual(
            FacultyTeacherAssignment.objects.get(user=self.faculty).pk, first.pk)


class AssignedInstructorsCopyForwardTests(AssignedInstructorsTabMixin, TestCase):
    def _copy(self, source, target=None):
        return self._post({
            'action': 'copy_assigned_instructors',
            'academic_year': str((target or self.year).id),
            'source_academic_year': str(source.id),
        })

    def _prepare(self):
        course = self._course('Copy')
        self._oversees(course)
        teacher = self._teacher()
        self._certifies(teacher, course)
        return course, teacher

    def test_copy_clones_the_source_years_rows(self):
        course, teacher = self._prepare()
        self._assign(teacher, course, year=self.other_year)

        html = self._copy(self.other_year)

        self.assertEqual(self._rows(), {(course.id, teacher.id)})
        # Cloned rows are left editable, in the target year's view.
        self.assertNotIn(UNASSIGNED_TEXT, html)
        self.assertIn(f'value="{self.year.id}" selected', html)

    def test_copy_stamps_the_acting_user_not_the_original_assigner(self):
        course, teacher = self._prepare()
        original = FacultyTeacherAssignment.objects.create(
            user=self.faculty, course=course, teacher=teacher,
            academic_year=self.other_year, created_by=self.faculty)

        self._copy(self.other_year)

        clone = FacultyTeacherAssignment.objects.get(academic_year=self.year)
        self.assertEqual(clone.created_by, self.ce_user)
        self.assertEqual(
            FacultyTeacherAssignment.objects.get(pk=original.pk).created_by,
            self.faculty)

    def test_copy_skips_existing_rows_without_raising(self):
        course, teacher = self._prepare()
        self._assign(teacher, course, year=self.other_year)
        existing = self._assign(teacher, course, year=self.year)

        self._copy(self.other_year)

        self.assertEqual(self._rows(), {(course.id, teacher.id)})
        self.assertEqual(
            FacultyTeacherAssignment.objects.get(academic_year=self.year).pk,
            existing.pk)

    def test_copy_from_an_empty_year_is_a_no_op(self):
        course, teacher = self._prepare()

        html = self._copy(self.other_year)

        self.assertEqual(self._rows(), set())
        self.assertIn(UNASSIGNED_TEXT, html)

    def test_copy_does_not_touch_another_faculty_members_rows(self):
        course, teacher = self._prepare()
        other_faculty = _user()
        CourseAdministrator.objects.create(
            course=course, user=other_faculty, status='Active')
        self._assign(teacher, course, year=self.other_year, user=other_faculty)

        self._copy(self.other_year)

        self.assertEqual(self._rows(), set())
        self.assertFalse(FacultyTeacherAssignment.objects.filter(
            user=other_faculty, academic_year=self.year).exists())

    def test_copy_to_the_same_year_is_a_no_op(self):
        course, teacher = self._prepare()
        self._assign(teacher, course, year=self.year)

        self._copy(self.year)

        self.assertEqual(self._rows(), {(course.id, teacher.id)})
        self.assertEqual(FacultyTeacherAssignment.objects.count(), 1)

    def test_copy_offers_the_other_years_as_sources(self):
        html = self._get()
        self.assertIn('source_academic_year', html)
        self.assertIn(str(self.other_year.name), html)
