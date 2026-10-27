"""/ce/api/teacher datatables row: pair-scoped columns and filters (#132).

Ported from nnu's faculty/tests/test_pair_scope.py (InstructorPairScopeTests).
Mike mentors An for ARDE1020 only, though she is also certified for ARDE2020,
which Mike oversees too; ARDE2020 is configured "No instructors". Stacy is
certified for ARDE1020 but not assigned.
"""
import uuid
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase

from cis.models.course import Campus, Cohort, Course, CourseAdministrator
from cis.models.faculty import (
    FacultyCoordinator, FacultyCourseAssignment, FacultyTeacherAssignment)
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherCourseCertificate, TeacherHighSchool
from cis.models.term import AcademicYear

User = get_user_model()
IN = 'In the Program'


def _sfx():
    return uuid.uuid4().hex[:8]


def _user(group=None):
    sfx = _sfx()
    user = User.objects.create_user(
        username=f'u_{sfx}', email=f'u_{sfx}@example.com', password='x',
        first_name='F', last_name='L')
    if group:
        user.groups.add(Group.objects.get_or_create(name=group)[0])
    return user


class TeacherFeedPairColumnTests(TestCase):

    def setUp(self):
        saved = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        self.addCleanup(setattr, user_logged_in, 'receivers', saved)

        for name in ('ce', 'faculty', 'instructor'):
            Group.objects.get_or_create(name=name)
        self.year = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.hs = HighSchool.objects.create(name=f'HS-{_sfx()}')
        # The ce branch runs through the campus gate: give the courses a
        # campus the ce user may process.
        self.campus = Campus.objects.create(
            name=f'Campus-{_sfx()}', code=f'{settings.CAMPUS_CODE_PREFIX}{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')

        self.mike = _user('faculty')
        FacultyCoordinator.objects.create(user=self.mike)

        def course(name):
            c = Course.objects.create(
                catalog_number=f'1{_sfx()}', title=name, name=name,
                cohort=cohort, campus=self.campus)
            CourseAdministrator.objects.create(
                course=c, user=self.mike, status='Active', role='Faculty')
            return c

        self.c1020 = course('ARDE1020')
        self.c2020 = course('ARDE2020')

        self.an = Teacher.objects.create(user=_user('instructor'), status='active')
        self.stacy = Teacher.objects.create(user=_user('instructor'), status='active')
        self._certify(self.an, self.c1020)
        self._certify(self.an, self.c2020)
        self._certify(self.stacy, self.c1020)

        FacultyTeacherAssignment.objects.create(
            user=self.mike, course=self.c1020, teacher=self.an,
            academic_year=self.year)
        FacultyCourseAssignment.objects.create(
            user=self.mike, course=self.c2020, academic_year=self.year)

        patcher = mock.patch('cis.services.faculty_scope.active_academic_year',
                             return_value=self.year)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.mike)

    def _certify(self, teacher, course, highschool=None, status=IN):
        ths, _ = TeacherHighSchool.objects.get_or_create(
            teacher=teacher, highschool=highschool or self.hs,
            defaults={'status': status})
        return TeacherCourseCertificate.objects.create(
            teacher_highschool=ths, course=course)

    def _get(self, **params):
        response = self.client.get('/ce/api/teacher/', {'format': 'datatables', **params})
        self.assertEqual(response.status_code, 200)
        return response.json()['data']

    def _rows(self, **params):
        return {r['id']: r for r in self._get(**params)}

    # -- columns ------------------------------------------------------------

    def test_course_column_lists_only_visible_pairs(self):
        row = self._rows()[str(self.an.id)]
        self.assertEqual(
            [c['course']['name'] for c in row['active_courses']], ['ARDE1020'])

    def test_high_school_column_lists_only_schools_of_visible_pairs(self):
        # An also teaches ARDE2020 at a second school; Mike doesn't mentor her
        # for ARDE2020, so that school isn't his to see on her row.
        self._certify(self.an, self.c2020,
                      highschool=HighSchool.objects.create(name=f'HS-{_sfx()}'))
        row = self._rows()[str(self.an.id)]
        self.assertEqual(row['active_highschools'], [self.hs.name])

    def test_high_school_column_follows_teachers_in_program_rule(self):
        left = HighSchool.objects.create(name=f'HS-{_sfx()}')
        self._certify(self.an, self.c1020, highschool=left, status='Not in the Program')
        self.assertEqual(
            self._rows()[str(self.an.id)]['active_highschools'], [self.hs.name])

        # Widen Teacher's rule and the faculty column follows it.
        with mock.patch.object(
                Teacher, 'in_program_teacher_highschools',
                lambda self: list(self.teacherhighschool_set.all())):
            row = self._rows()[str(self.an.id)]
        self.assertEqual(sorted(row['active_highschools']),
                         sorted([self.hs.name, left.name]))

    def test_ce_course_column_is_unchanged(self):
        ce = _user('ce')
        ce.set_process_campuses([str(self.campus.id)])
        self.client.force_login(ce)
        row = self._rows()[str(self.an.id)]
        self.assertEqual(
            sorted(c['course']['name'] for c in row['active_courses']),
            ['ARDE1020', 'ARDE2020'])

    def test_columns_naming_the_field_keep_it(self):
        row = self._rows(**{'columns[0][data]': 'id',
                            'columns[1][data]': 'active_courses'})[str(self.an.id)]
        self.assertIn('active_courses', row)
        self.assertNotIn('active_highschools', row)

    def test_columns_not_naming_them_drop_both(self):
        row = self._rows(**{'columns[0][data]': 'id',
                            'columns[1][data]': 'user.last_name'})[str(self.an.id)]
        self.assertNotIn('active_courses', row)
        self.assertNotIn('active_highschools', row)

    # -- filters ------------------------------------------------------------

    def test_course_filter_matches_only_visible_pairs(self):
        # "Who do I mentor for ARDE2020?" -- nobody. An is visible through
        # ARDE1020 and certified for ARDE2020, but that pair isn't Mike's.
        self.assertEqual(self._get(course=str(self.c2020.id)), [])
        self.assertEqual([r['id'] for r in self._get(course=str(self.c1020.id))],
                         [str(self.an.id)])

    def test_high_school_filter_matches_only_schools_of_visible_pairs(self):
        other = HighSchool.objects.create(name=f'HS-{_sfx()}')
        self._certify(self.an, self.c2020, highschool=other)
        self.assertEqual(self._get(highschool=str(other.id)), [])
        self.assertEqual([r['id'] for r in self._get(highschool=str(self.hs.id))],
                         [str(self.an.id)])

    def test_ce_filters_use_every_certificate(self):
        ce = _user('ce')
        ce.set_process_campuses([str(self.campus.id)])
        self.client.force_login(ce)
        self.assertEqual({r['id'] for r in self._get(course=str(self.c1020.id))},
                         {str(self.an.id), str(self.stacy.id)})
        left = HighSchool.objects.create(name=f'HS-{_sfx()}')
        self._certify(self.stacy, self.c2020, highschool=left, status='Not in the Program')
        self.assertEqual(self._get(highschool=str(left.id)), [])

    def test_malformed_filter_ids_match_nothing(self):
        self.assertEqual(self._get(course='nope'), [])
        self.assertEqual(self._get(highschool='nope'), [])
