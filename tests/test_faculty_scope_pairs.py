"""Faculty -> instructor mapping by (course, teacher) pair (package-faculty#2).

- A course configured for a year shows exactly its assigned instructors --
  possibly none (FacultyCourseAssignment with no assignment rows).
- Unconfigured courses fall back to every certified instructor, as before.
- A section is judged against its own term's academic year (D1).
"""
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase

from cis.models.course import CourseAdministrator
from cis.models.faculty import FacultyCourseAssignment, FacultyYearSetup
from cis.models.section import ClassSection
from cis.models.teacher import TeacherCourseCertificate
from cis.models.term import Term
from cis.services import faculty_scope

from .test_faculty_scope import FacultyScopeFixtureMixin, _suffix


class PairScopeTests(FacultyScopeFixtureMixin, TestCase):

    def setUp(self):
        super().setUp()
        # Deb's example, shrunk: Ji Soo An teaches ARDE1020 and ARDE2020; Mike
        # mentors her for ARDE1020 only. Stacy is certified for ARDE1020 too.
        self.c1020 = self._course('ARDE1020')
        self.c2020 = self._course('ARDE2020')
        for c in (self.c1020, self.c2020):
            self._oversees(c)
        self.an = self._teacher()
        self.stacy = self._teacher()
        self._certifies(self.an, self.c1020)
        self._certifies(self.an, self.c2020)
        self._certifies(self.stacy, self.c1020)
        self.term = Term.objects.create(
            academic_year=self.year, code='FA', label=f'Fall-{_suffix()}')
        self.other_term = Term.objects.create(
            academic_year=self.other_year, code='FA', label=f'Fall-{_suffix()}')
        self.active = mock.patch('cis.services.faculty_scope.active_academic_year',
                                 return_value=self.year)
        self.active.start()
        self.addCleanup(self.active.stop)

    def _configure(self, course, year=None):
        return FacultyCourseAssignment.objects.create(
            user=self.faculty, course=course, academic_year=year or self.year)

    def _section(self, course, teacher, term=None):
        return ClassSection.objects.create(
            term=term or self.term, course=course, highschool=self.hs, teacher=teacher)

    def _visible_sections(self, *sections):
        return set(ClassSection.objects.filter(
            id__in=[s.id for s in sections]
        ).filter(faculty_scope.visible_pairs_q(
            self.faculty, course_field='course_id', teacher_field='teacher_id',
            year_field='term__academic_year', require_certificate=False,
        )).values_list('id', flat=True))

    def pairs(self):
        return faculty_scope.visible_course_teachers(self.faculty)

    # -- the configuration model -----------------------------------------

    def test_configuration_is_unique_per_user_course_year(self):
        self._configure(self.c1020)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._configure(self.c1020)

    def test_configuration_cascades_with_the_course(self):
        # A course with no certificates: those PROTECT their course.
        bare = self._course('BARE')
        self._configure(bare)
        bare.delete()
        self.assertFalse(FacultyCourseAssignment.objects.exists())

    # -- pairs -------------------------------------------------------------

    def test_unconfigured_courses_show_every_certified_pair(self):
        self.assertEqual(self.pairs(), {
            (self.c1020.id, self.an.id), (self.c2020.id, self.an.id),
            (self.c1020.id, self.stacy.id)})

    def test_assigned_on_one_course_is_one_pair(self):
        self._assign(self.an, self.c1020)
        # ARDE1020 is configured: only An. ARDE2020 is not: still falls back.
        self.assertEqual(self.pairs(), {
            (self.c1020.id, self.an.id), (self.c2020.id, self.an.id)})

    def test_configured_with_no_instructors_shows_none_for_that_course(self):
        self._configure(self.c2020)
        self.assertEqual(self.pairs(), {
            (self.c1020.id, self.an.id), (self.c1020.id, self.stacy.id)})

    def test_configured_course_drops_out_of_visible_teachers(self):
        self._configure(self.c1020)
        self._configure(self.c2020)
        self.assertFalse(faculty_scope.visible_teachers(self.faculty).exists())

    def test_assignments_saved_before_the_model_still_configure(self):
        self._assign(self.stacy, self.c1020)
        self.assertNotIn((self.c1020.id, self.an.id), self.pairs())

    def test_inactive_course_row_shows_nothing(self):
        CourseAdministrator.objects.filter(user=self.faculty).update(status='Inactive')
        self.assertEqual(self.pairs(), set())

    def test_one_query_for_any_number_of_courses(self):
        for i in range(5):
            c = self._course(f'X{i}')
            self._oversees(c)
            self._certifies(self.stacy, c)
        with self.assertNumQueries(1):
            self.pairs()

    # -- sections, judged by their own year (D1) ---------------------------

    def test_sections_follow_the_pairs(self):
        self._assign(self.an, self.c1020)
        self._configure(self.c2020)
        an_1020 = self._section(self.c1020, self.an)
        an_2020 = self._section(self.c2020, self.an)
        stacy_1020 = self._section(self.c1020, self.stacy)
        self.assertEqual(self._visible_sections(an_1020, an_2020, stacy_1020), {an_1020.id})

    def test_unconfigured_course_shows_every_section_even_without_a_certificate(self):
        stranger = self._teacher()
        section = self._section(self.c2020, stranger)
        self.assertEqual(self._visible_sections(section), {section.id})

    def test_a_section_uses_its_own_terms_year(self):
        # Configured (nobody) for this year only; last year is not set up, so
        # with year_field its sections show nothing either (FacultyYearSetup).
        self._configure(self.c2020)
        this_year = self._section(self.c2020, self.an)
        other_year = self._section(self.c2020, self.an, term=self.other_term)
        self.assertEqual(self._visible_sections(this_year, other_year), set())
        FacultyYearSetup.objects.create(user=self.faculty, academic_year=self.other_year)
        self.assertEqual(self._visible_sections(this_year, other_year), {other_year.id})

    # -- year setup (package-faculty#3) -------------------------------------

    def test_set_up_for_another_year_only_shows_nothing(self):
        FacultyYearSetup.objects.create(user=self.faculty, academic_year=self.other_year)
        section = self._section(self.c1020, self.an)
        self.assertEqual(self.pairs(), set())
        self.assertFalse(faculty_scope.visible_teachers(self.faculty).exists())
        self.assertEqual(self._visible_sections(section), set())

    def test_legacy_rows_in_another_year_count_as_set_up(self):
        self._assign(self.an, self.c1020, year=self.other_year)
        self.assertEqual(self.pairs(), set())

    def test_a_year_set_up_with_every_course_on_all_shows_everyone(self):
        FacultyYearSetup.objects.create(user=self.faculty, academic_year=self.other_year)
        FacultyYearSetup.objects.create(user=self.faculty, academic_year=self.year)
        self.assertEqual(len(self.pairs()), 3)

    def test_another_mentors_setup_does_not_affect_this_one(self):
        from .test_faculty_scope import _user
        FacultyYearSetup.objects.create(user=_user(), academic_year=self.other_year)
        self.assertEqual(len(self.pairs()), 3)

    def test_no_active_year_with_a_setup_shows_nothing(self):
        FacultyYearSetup.objects.create(user=self.faculty, academic_year=self.year)
        with mock.patch('cis.services.faculty_scope.active_academic_year',
                        return_value=None):
            self.assertEqual(self.pairs(), set())

    def test_unoverseen_course_sections_are_never_visible(self):
        theirs = self._course('THEIRS')
        self._certifies(self.an, theirs)
        self.assertEqual(self._visible_sections(self._section(theirs, self.an)), set())
