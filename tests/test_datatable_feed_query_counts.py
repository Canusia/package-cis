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

    def test_teacher_active_courses_reads_the_prefetch_cache(self):
        teacher = eager.with_teacher_related(
            Teacher.objects.filter(pk=self.teacher.pk)).get()
        with CaptureQueriesContext(connection) as captured:
            courses = list(teacher.active_courses)
        self.assertEqual(len(captured.captured_queries), 0)
        self.assertEqual(len(courses), 1)

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
