"""Query-count regression tests for the CE DataTables feeds (issue #67).

Every router-registered CE viewset used to return a bare queryset while its
serializer walked a deep nest, so serialization issued a couple of dozen
queries per row. On RDS (~5-7 ms a round trip) that is what made
/ce/registrations/ take seconds per sort click, and /ce/sections/ was next in
line at 22 queries per row.

Two things had to change, and both are pinned here:

* the viewsets now apply a relation plan from ``cis.views.eager``;
* the properties those plans have to reach through -- ``Course.uploads`` and
  its two filtered variants, ``ClassSection.syllabi`` and
  ``Teacher.active_courses`` -- used to build a fresh queryset on every access,
  which defeated any prefetch. They now read the reverse manager / prefetch
  cache, so ``PrefetchAwarePropertyTests`` guards the mechanism itself: break
  it and every plan silently degrades back to an N+1 while still returning
  correct data.

Query counts are measured with the queryset evaluated **inside** the capture,
because a ``prefetch_related``'s own queries fire on evaluation; measuring only
serialization would hide them and flatter the eager path.
"""

import uuid

from django.contrib.auth.models import Group
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from cis.models import CustomUser
from cis.models.course import (
    Campus, Category, Cohort, Course, CourseUpload, Location)
from cis.models.district import District
from cis.models.highschool import HighSchool
from cis.models.note import ClassSectionNote, CourseNote, TeacherNote
from cis.models.section import (
    ClassSection, ClassSectionSyllabi, StudentDropRequest, StudentRegistration)
from cis.models.student import Student
from cis.models.teacher import (
    Teacher, TeacherCourseCertificate, TeacherHighSchool)
from cis.models.term import AcademicYear, Term
from cis.serializers.class_section import ClassSectionSerializer
from cis.serializers.course import CourseSerializer
from cis.serializers.highschool import (
    HighSchoolTeacherSerializer, TeacherCourseSerializer)
from cis.serializers.note import (
    ClassSectionNoteSerializer, CourseNoteSerializer, TeacherNoteSerializer)
from cis.serializers.registration import (
    StudentDropRequestSerializer, StudentRegistrationSerializer)
from cis.serializers.teacher import TeacherSerializer
from cis.views import eager


def _short():
    return uuid.uuid4().hex[:8]


class FeedFixture:
    """One fully-populated row's worth of every relation the feeds walk.

    Each call builds its own campus/course/section/teacher/student graph, so
    N calls give N rows that share nothing -- which is what makes an N+1 cost
    N queries instead of being masked by Django's per-instance caching.
    """

    @staticmethod
    def build():
        short = _short()

        Group.objects.get_or_create(name='student')
        Group.objects.get_or_create(name='instructor')
        staff, _ = CustomUser.objects.get_or_create(
            username='feed-staff',
            defaults={'email': 'feed-staff@example.com'})
        # The registration post_save signal attributes its auto-note to 'cron'.
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})

        campus = Campus.objects.create(name=f'Campus-{short}', code=short)
        campus.locations.add(Location.objects.create(name=f'Loc-{short}'))

        cohort = Cohort.objects.create(name=f'Cohort-{short}', designator='A')
        category = Category.objects.create(name=f'Cat-{short}')
        course = Course.objects.create(
            catalog_number='001', title='Descriptive Astronomy',
            name=f'A {short}', cohort=cohort, category=category,
            campus=campus)

        # One upload of each media type this tenant's three upload properties
        # select on, so each returns something.
        for media_type in ('Syllabus Template', 'Course Resource',
                           'Shared Resource'):
            CourseUpload.objects.create(
                course=course, media_type=media_type,
                media=f'{short}-{media_type}.pdf')

        academic_year = AcademicYear.objects.create(
            name=f'AY-{short}', campus=campus)
        term = Term.objects.create(
            label=f'Term-{short}', code=short, academic_year=academic_year)

        district = District.objects.create(name=f'District-{short}')
        highschool = HighSchool.objects.create(
            name=f'HS-{short}', code=short, district=district)

        teacher_user = CustomUser.objects.create_user(
            username=f'tch-{short}', email=f'tch-{short}@example.com',
            password='x', first_name='Tess', last_name='Teacher')
        teacher = Teacher.objects.create(user=teacher_user)
        teacher_highschool = TeacherHighSchool.objects.create(
            teacher=teacher, highschool=highschool, status='In the Program')
        TeacherCourseCertificate.objects.create(
            teacher_highschool=teacher_highschool, course=course)

        section = ClassSection.objects.create(
            course=course, term=term, registration_term=term,
            campus=campus, highschool=highschool, teacher=teacher,
            class_number=f'A-{short}', section_number='3428',
            external_sis_id=uuid.uuid4(), meta={},
        )
        syllabus = ClassSectionSyllabi.objects.create(
            media=f'{short}-syllabus.pdf')
        syllabus.class_sections.add(section)

        student_user = CustomUser.objects.create_user(
            username=f'stu-{short}', email=f'stu-{short}@example.com',
            password='x', first_name='Avi', last_name='Codtest')
        student = Student.objects.create(
            user=student_user, sis_id=uuid.uuid4(), highschool=highschool)

        registration = StudentRegistration.objects.create(
            student=student, class_section=section,
            status='applied', status_changed_on={'applied_on': '01/01/2026'},
            highschool=highschool,
        )

        ClassSectionNote.objects.create(
            class_section=section, createdby=staff, note='section note',
            meta={})
        CourseNote.objects.create(
            course=course, createdby=staff, note='course note')
        TeacherNote.objects.create(
            teacher=teacher, createdby=staff, note='teacher note',
            meta={'type': ''})
        StudentDropRequest.objects.create(
            student=student, registration=registration, status='requested')

        return registration


def _cost(queryset, serializer_class, limit):
    """(rows, queries) for serializing `limit` rows of `queryset`.

    The evaluation happens inside the capture on purpose -- see the module
    docstring.
    """
    with CaptureQueriesContext(connection) as captured:
        rows = list(queryset.order_by('id')[:limit])
        serializer_class(rows, many=True).data
    return len(rows), len(captured.captured_queries)


class PrefetchAwarePropertyTests(TestCase):
    """The model properties the plans depend on must honour the prefetch.

    These are the load-bearing part of the fix: if any of them goes back to
    building a fresh queryset, the feeds keep returning correct data and
    quietly regress to an N+1.
    """

    @classmethod
    def setUpTestData(cls):
        cls.registration = FeedFixture.build()
        cls.course = cls.registration.class_section.course
        cls.section = cls.registration.class_section
        cls.teacher = cls.section.teacher

    def test_course_upload_properties_use_the_prefetch_cache(self):
        course = Course.objects.prefetch_related('courseupload_set').get(
            pk=self.course.pk)
        with CaptureQueriesContext(connection) as captured:
            uploads = list(course.uploads)
            syllabi = list(course.syllabi_uploads)
            shared = list(course.shared_resource_uploads)
        self.assertEqual(len(captured.captured_queries), 0)
        self.assertEqual(len(uploads), 3)
        self.assertEqual(
            [u.media_type for u in syllabi], ['Syllabus Template'])
        self.assertEqual(
            sorted(u.media_type for u in shared),
            ['Course Resource', 'Shared Resource'])

    def test_upload_properties_agree_with_the_unprefetched_path(self):
        fresh = Course.objects.get(pk=self.course.pk)
        cached = Course.objects.prefetch_related('courseupload_set').get(
            pk=self.course.pk)
        for name in ('uploads', 'syllabi_uploads', 'shared_resource_uploads'):
            with self.subTest(prop=name):
                self.assertEqual(
                    sorted(u.pk for u in getattr(fresh, name)),
                    sorted(u.pk for u in getattr(cached, name)))

    def test_class_section_syllabi_uses_the_prefetch_cache(self):
        section = ClassSection.objects.prefetch_related(
            'classsectionsyllabi_set').get(pk=self.section.pk)
        with CaptureQueriesContext(connection) as captured:
            syllabi = list(section.syllabi)
            links = section.syllabi_links
        self.assertEqual(len(captured.captured_queries), 0)
        self.assertEqual(len(syllabi), 1)
        self.assertEqual(len(links), 1)

    def test_syllabi_agrees_with_the_unprefetched_path(self):
        fresh = ClassSection.objects.get(pk=self.section.pk)
        cached = ClassSection.objects.prefetch_related(
            'classsectionsyllabi_set').get(pk=self.section.pk)
        self.assertEqual(
            sorted(s.pk for s in fresh.syllabi),
            sorted(s.pk for s in cached.syllabi))

    def test_teacher_properties_read_the_prefetch_cache(self):
        teacher = eager.with_teacher_related(
            Teacher.objects.filter(pk=self.teacher.pk)).get()
        with CaptureQueriesContext(connection) as captured:
            courses = list(teacher.active_courses)
            highschools = list(teacher.active_highschools)
        self.assertEqual(len(captured.captured_queries), 0)
        self.assertEqual(len(courses), 1)
        self.assertEqual(len(highschools), 1)

    def test_active_highschools_agrees_with_the_unprefetched_path(self):
        """The un-prefetched branch must keep returning the values_list
        queryset: the teacher-certificate CSV report force_str()s this field
        and never prefetches."""
        fresh = Teacher.objects.get(pk=self.teacher.pk)
        cached = eager.with_teacher_related(
            Teacher.objects.filter(pk=self.teacher.pk)).get()
        self.assertEqual(list(fresh.active_highschools),
                         list(cached.active_highschools))
        self.assertNotIsInstance(fresh.active_highschools, list)

    def test_teacher_active_courses_still_works_unprefetched(self):
        fresh = Teacher.objects.get(pk=self.teacher.pk)
        cached = eager.with_teacher_related(
            Teacher.objects.filter(pk=self.teacher.pk)).get()
        self.assertEqual(
            [c.pk for c in fresh.active_courses],
            [c.pk for c in cached.active_courses])

    def test_partially_prefetched_teacher_falls_back_to_the_query(self):
        """Sections cached but certificates not: the for/else must re-query
        rather than return an empty list."""
        teacher = Teacher.objects.prefetch_related(
            'teacherhighschool_set').get(pk=self.teacher.pk)
        self.assertEqual(
            [c.pk for c in teacher.active_courses],
            [c.pk for c in Teacher.objects.get(
                pk=self.teacher.pk).active_courses])


class DataTableFeedQueryCountTests(TestCase):
    """Each feed must beat its bare queryset and stay inside a per-row budget.

    `budget` is generous: it exists to catch a serializer or property change
    that reintroduces an N+1, not to pin today's exact number.
    """

    ROWS = 5

    # (label, model, plan, serializer, per-row budget, marginal allowance)
    #
    # `marginal` is the number of queries each *additional* row is still
    # allowed to cost, and it is the sharper of the two numbers: everything a
    # plan eager-loads is a constant, so a non-zero marginal is exactly the
    # per-row work no plan can remove. The feeds that carry one are the ones
    # whose serializers dereference things that are not relations at all:
    #
    #   class_section (3)  ClassSection.is_a_co_req (a reverse existence check),
    #                      has_visit_to_other_section (a cross-app VisitSchedule
    #                      lookup keyed on term+teacher+course), and the
    #                      enrolment counts.
    #   registration (6)   the three above, reached through class_section, plus
    #                      StudentRegistration.has_signed_parent_consent,
    #                      has_signed_student_agreement and has_recommendation().
    #
    # Removing those needs annotations, not eager loading, so they are recorded
    # rather than fixed here. Every other feed must stay flat at 0.
    FEEDS = (
        ('class_section', ClassSection,
         eager.with_class_section_related, ClassSectionSerializer, 5, 3),
        ('class_section_notes', ClassSectionNote,
         eager.with_class_section_note_related, ClassSectionNoteSerializer, 5, 3),
        ('course', Course,
         eager.with_course_related, CourseSerializer, 1, 0),
        ('course-notes', CourseNote,
         eager.with_course_note_related, CourseNoteSerializer, 1, 0),
        ('teacher', Teacher,
         eager.with_teacher_related, TeacherSerializer, 1, 0),
        ('teacher-notes', TeacherNote,
         eager.with_teacher_note_related, TeacherNoteSerializer, 1, 0),
        ('teacher-course', TeacherCourseCertificate,
         eager.with_teacher_course_related, TeacherCourseSerializer, 2, 0),
        ('highschool-teacher', TeacherHighSchool,
         eager.with_teacher_highschool_related, HighSchoolTeacherSerializer, 1, 0),
        ('registration', StudentRegistration,
         eager.with_registration_related, StudentRegistrationSerializer, 9, 6),
        ('drop_wd_req', StudentDropRequest,
         eager.with_drop_request_related, StudentDropRequestSerializer, 9, 6),
    )

    @classmethod
    def setUpTestData(cls):
        for _ in range(cls.ROWS):
            FeedFixture.build()

    def test_every_feed_beats_its_bare_queryset(self):
        for label, model, plan, serializer_class, _, _ in self.FEEDS:
            with self.subTest(feed=label):
                rows, bare = _cost(
                    model.objects.all(), serializer_class, self.ROWS)
                self.assertEqual(rows, self.ROWS, 'fixture did not build rows')
                _, planned = _cost(
                    plan(model.objects.all()), serializer_class, self.ROWS)
                self.assertLess(
                    planned, bare / 2,
                    f'{label}: eager feed used {planned} queries vs {bare} '
                    f'bare; expected at least 2x better')

    def test_every_feed_stays_within_its_per_row_budget(self):
        for label, model, plan, serializer_class, budget, _ in self.FEEDS:
            with self.subTest(feed=label):
                rows, planned = _cost(
                    plan(model.objects.all()), serializer_class, self.ROWS)
                per_row = planned / rows
                self.assertLessEqual(
                    per_row, budget,
                    f'{label}: {per_row:.1f} queries per row exceeds the '
                    f'budget of {budget}')

    def test_each_extra_row_costs_no_more_than_its_marginal_allowance(self):
        """The real N+1 check: what does one *more* row cost?

        A plan can look fine at a fixed row count and still be linear -- a
        per-row query plus a small constant reads the same as a constant plan
        when you only measure once. Differencing two row counts cancels the
        constant and leaves the per-row term, which is the thing that turns
        into seconds on a 100-row page.
        """
        for label, model, plan, serializer_class, _, marginal in self.FEEDS:
            with self.subTest(feed=label):
                _, few = _cost(plan(model.objects.all()), serializer_class, 2)
                rows, many = _cost(
                    plan(model.objects.all()), serializer_class, self.ROWS)
                per_extra_row = (many - few) / (rows - 2)
                self.assertLessEqual(
                    per_extra_row, marginal,
                    f'{label}: each row beyond the first two cost '
                    f'{per_extra_row:.1f} queries ({few} for 2 rows, {many} '
                    f'for {rows}); the allowance is {marginal}')


class ViewsetAppliesItsPlanTests(TestCase):
    """A plan that exists but is never bound is the failure this catches.

    The plans are attached with the ``@eager_queryset`` decorator rather than
    at each ``return``, so what has to be pinned is that every viewset carries
    the decorator and that its ``get_queryset()`` really does come back
    planned -- including down whichever branch a bare request takes.
    """

    # (basename, expects select_related, expects prefetch_related)
    #
    # `class-registered` needs a campus_id: ClassesRegisteredByCampusViewSet
    # feeds the raw GET value into a UUIDField lookup, so a bare request
    # raises ValidationError -> 500. That is a pre-existing missing non-UUID
    # guard, not something these plans introduce or fix, so the test supplies
    # a real campus rather than asserting on the crash.
    #
    # with_highschool_administrator_related is select_related only, and
    # with_class_section_syllabi_related is prefetch only, so the two are
    # asserted separately rather than with a single "is it eager" check that
    # both could pass for the wrong reason.
    VIEWSETS = (
        ('class_section', True, True),
        ('class-registered', True, True),
        ('class_section_notes', True, True),
        ('class_section_syllabi', False, True),
        ('course', True, True),
        ('course-notes', True, True),
        ('course-uploads', True, True),
        ('course-app-requirement', True, True),
        ('teacher', True, True),
        ('teacher-notes', True, True),
        ('teacher-course', True, True),
        ('highschool-teacher', True, True),
        ('highschool-administrator', True, False),
        ('teacher_application_reviewers', True, False),
        ('registration', True, True),
        ('drop_wd_req', True, True),
    )

    PARAMS = {}

    @classmethod
    def setUpTestData(cls):
        registration = FeedFixture.build()
        cls.user = CustomUser.objects.create_superuser(
            username='plan-check', email='plan-check@example.com',
            password='x')
        section = registration.class_section
        cls.PARAMS = {
            'class-registered': {
                'campus_id': str(section.course.campus_id),
                'term_id': str(section.term_id),
            },
        }

    def _queryset_for(self, basename, params=None):
        from rest_framework.test import APIRequestFactory

        from cis.urls import router_viewsets

        request = APIRequestFactory().get('/x', params or {})
        request.user = self.user
        view = router_viewsets[basename]()
        view.request = request
        view.format_kwarg = None
        return view.get_queryset()

    def test_every_feed_viewset_returns_a_planned_queryset(self):
        for basename, wants_select, wants_prefetch in self.VIEWSETS:
            with self.subTest(feed=basename):
                qs = self._queryset_for(basename, self.PARAMS.get(basename))
                if wants_select:
                    self.assertTrue(
                        qs.query.select_related,
                        f'{basename}: get_queryset() returned a queryset with '
                        f'no select_related; is @eager_queryset missing?')
                if wants_prefetch:
                    self.assertTrue(
                        qs._prefetch_related_lookups,
                        f'{basename}: get_queryset() returned a queryset with '
                        f'no prefetch_related; is @eager_queryset missing?')
