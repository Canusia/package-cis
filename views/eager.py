"""Eager-loading plans for the CE DataTables feeds.

Every router-registered CE viewset returns a bare queryset while its serializer
walks a deep nest of relations, so serialization issues a couple of dozen
queries per row. On RDS (~5-7 ms per round trip, against ~0.15 ms locally) that
is what turned /ce/registrations/ into the "about 6 seconds per sort click" the
client reported, and /ce/sections/ was on the same trajectory (issue #67).

This module holds the relation plans in one place, because the same nests are
reached through many different tables: ClassSectionSerializer is used by the
sections feed, the by-campus feed, the section notes feed and the syllabi feed;
CourseSerializer is nested under all of those plus the courses, course notes,
course uploads and teacher certificate feeds.

Three rules govern what belongs in a plan:

* **Only *declared* nested serializers matter.** An undeclared FK under
  ``fields = '__all__'`` becomes a ``PrimaryKeyRelatedField``, which DRF
  resolves from the local ``*_id`` column without touching the DB. Adding it to
  ``select_related`` only widens the join for nothing.
* **``datatables_always_serialize`` saves nothing.** drf-datatables trims fields
  in ``DatatablesRenderer._filter_unused_fields()``, i.e. *after* the serializer
  has run and issued every query.
* **A property that builds a fresh queryset cannot be prefetched.**
  ``Course.uploads``, ``ClassSection.syllabi`` and ``Teacher.active_courses``
  were exactly that; they were rewritten to go through the reverse managers (or
  to read the prefetch cache) so the plans below can reach them. The ones that
  remain -- ``ClassSection.has_visit_to_other_section``, ``is_a_co_req``, and
  the ``StudentRegistration.has_signed_*`` checks -- still cost a query per row
  and can only be removed by annotating or trimming the serializer.

Each plan comes in three parts: a ``*_select_related(prefix)`` tuple, a
``*_prefetch_related(prefix)`` tuple, and a ``with_*_related(records)`` helper
that applies both. The ``prefix`` argument is what lets a parent plan embed a
child one -- ``course_select_related('class_section__course__')`` -- so the
paths are written once and reused at any depth.
"""

from django.db.models import Prefetch


def prefixed(prefix, paths):
    """Re-root a tuple of relation paths under ``prefix``."""
    return tuple(prefix + path for path in paths)


# --------------------------------------------------------------------------
# Course -- CourseSerializer(category, cohort, campus, uploads,
#           syllabi_uploads, shared_resource_uploads)
# --------------------------------------------------------------------------

def course_select_related(prefix=''):
    return prefixed(prefix, ('cohort', 'category', 'campus'))


def course_prefetch_related(prefix=''):
    # CampusSerializer nests locations; all three upload properties read the
    # single `courseupload_set` cache.
    return prefixed(prefix, ('campus__locations', 'courseupload_set'))


def with_course_related(records):
    return records.select_related(
        *course_select_related()
    ).prefetch_related(
        *course_prefetch_related()
    )


# --------------------------------------------------------------------------
# Teacher -- TeacherSerializer(user, active_courses)
# --------------------------------------------------------------------------

def teacher_select_related(prefix=''):
    return prefixed(prefix, ('user',))


def teacher_prefetch_related(prefix=''):
    """Feed Teacher.active_courses from cache.

    The property walks Teacher -> TeacherHighSchool -> TeacherCourseCertificate,
    which no single relation path covers, so it reads this prefetch's cache
    instead (see cis/models/teacher.py). The certificates are serialized with a
    nested CourseSerializer, hence the course plan inside.
    """
    from cis.models.teacher import TeacherCourseCertificate, TeacherHighSchool

    certificates = Prefetch(
        'teachercoursecertificate_set',
        queryset=TeacherCourseCertificate.objects.select_related(
            *course_select_related('course__')
        ).prefetch_related(
            *course_prefetch_related('course__')
        ),
    )
    return (
        Prefetch(
            prefix + 'teacherhighschool_set',
            queryset=TeacherHighSchool.objects.select_related(
                'highschool'
            ).prefetch_related(certificates),
        ),
    )


def with_teacher_related(records):
    return records.select_related(
        *teacher_select_related()
    ).prefetch_related(
        *teacher_prefetch_related()
    )


# --------------------------------------------------------------------------
# ClassSection -- ClassSectionSerializer(course, campus, highschool, co_reqs,
#                 syllabi, location, term, registration_term, teacher)
# --------------------------------------------------------------------------

def term_select_related(prefix=''):
    """TermSerializer(academic_year, parent); its `campus` field reads
    `academic_year.campus`."""
    return prefixed(prefix, ('academic_year__campus', 'parent'))


def campus_prefetch_related(prefix=''):
    """CampusSerializer nests locations."""
    return prefixed(prefix, ('locations',))


def class_section_select_related(prefix=''):
    # Term appears twice (term and registration_term).
    return (
        course_select_related(prefix + 'course__')
        + prefixed(prefix, ('campus', 'highschool__district', 'location'))
        + term_select_related(prefix + 'term__')
        + term_select_related(prefix + 'registration_term__')
        + teacher_select_related(prefix + 'teacher__')
    )


def class_section_prefetch_related(prefix=''):
    from cis.models.section import ClassSection

    return (
        course_prefetch_related(prefix + 'course__')
        + campus_prefetch_related(prefix + 'campus__')
        # ClassSection.syllabi reads this cache.
        + prefixed(prefix, ('classsectionsyllabi_set',))
        + teacher_prefetch_related(prefix + 'teacher__')
        + (
            # ClassSectionCoReqSerializer reads obj.course.name and
            # obj.course.credit_hours through SerializerMethodFields.
            Prefetch(
                prefix + 'co_reqs',
                queryset=ClassSection.objects.select_related('course'),
            ),
        )
    )


def with_class_section_related(records):
    return records.select_related(
        *class_section_select_related()
    ).prefetch_related(
        *class_section_prefetch_related()
    )


# --------------------------------------------------------------------------
# Student / StudentRegistration -- StudentSerializer(user, highschool);
# StudentRegistrationSerializer(class_section, student, highschool, reviewer)
# --------------------------------------------------------------------------

def student_select_related(prefix=''):
    return prefixed(prefix, ('user', 'highschool__district'))


def registration_select_related(prefix=''):
    return (
        class_section_select_related(prefix + 'class_section__')
        + student_select_related(prefix + 'student__')
        + prefixed(prefix, ('highschool__district', 'reviewer__user'))
    )


def registration_prefetch_related(prefix=''):
    from django.apps import apps

    from cis.models.sis import SIS_Log

    # ethos ships either flat (`ethos.models`) or nested under the editable
    # submodule (`ethos.ethos.models`); the app registry is right either way.
    EthosLog = apps.get_model('ethos', 'EthosLog')

    # `fields = '__all__'` renders these M2Ms as PrimaryKeyRelatedField(many=True),
    # so only the pk is used -- but the rows carry whole SIS request/response
    # payloads, so fetch just the id and keep the response out of memory.
    return (
        class_section_prefetch_related(prefix + 'class_section__')
        + (
            Prefetch(prefix + 'sis_log', queryset=SIS_Log.objects.only('id')),
            Prefetch(prefix + 'mirror_logs', queryset=EthosLog.objects.only('id')),
        )
    )


def with_registration_related(records):
    return records.select_related(
        *registration_select_related()
    ).prefetch_related(
        *registration_prefetch_related()
    ).order_by('-created_on')


def with_drop_request_related(records):
    """StudentDropRequestSerializer(student, registration -> the whole
    registration nest)."""
    return records.select_related(
        *student_select_related('student__'),
        *registration_select_related('registration__'),
    ).prefetch_related(
        *registration_prefetch_related('registration__')
    )


# --------------------------------------------------------------------------
# Tables that nest one of the plans above
# --------------------------------------------------------------------------

def with_class_section_note_related(records):
    """ClassSectionNoteSerializer(createdby, class_section)."""
    return records.select_related(
        'createdby', *class_section_select_related('class_section__')
    ).prefetch_related(
        *class_section_prefetch_related('class_section__')
    )


def with_course_note_related(records):
    """CourseNoteSerializer(createdby, course)."""
    return records.select_related(
        'createdby', *course_select_related('course__')
    ).prefetch_related(
        *course_prefetch_related('course__')
    )


def with_course_upload_related(records):
    """CourseUploadSerializer(course) / CourseAppRequirementSerializer(course)."""
    return records.select_related(
        *course_select_related('course__')
    ).prefetch_related(
        *course_prefetch_related('course__')
    )


def with_teacher_note_related(records):
    """TeacherNoteSerializer(createdby, teacher)."""
    return records.select_related(
        'createdby', *teacher_select_related('teacher__')
    ).prefetch_related(
        *teacher_prefetch_related('teacher__')
    )


def with_teacher_highschool_related(records):
    """HighSchoolTeacherSerializer(teacher, highschool)."""
    return records.select_related(
        *teacher_select_related('teacher__'), 'highschool__district'
    ).prefetch_related(
        *teacher_prefetch_related('teacher__')
    )


def with_teacher_course_related(records):
    """TeacherCourseSerializer / TeacherCourseCertificateSerializer
    (course, teacher_highschool -> teacher, highschool)."""
    return records.select_related(
        *course_select_related('course__'),
        *teacher_select_related('teacher_highschool__teacher__'),
        'teacher_highschool__highschool__district',
    ).prefetch_related(
        *course_prefetch_related('course__'),
        *teacher_prefetch_related('teacher_highschool__teacher__'),
    )


def with_highschool_administrator_related(records):
    """HighSchoolAdministratorSerializer(hsadmin -> user, position,
    highschool -> district)."""
    return records.select_related(
        'hsadmin__user', 'position', 'highschool__district'
    )


def with_class_section_syllabi_related(records):
    """ClassSectionSyllabiSerializer(class_sections -> the whole section nest)."""
    from cis.models.section import ClassSection

    return records.prefetch_related(
        Prefetch(
            'class_sections',
            queryset=with_class_section_related(ClassSection.objects.all()),
        )
    )


def with_applicant_course_reviewer_related(records):
    """ApplicantCourseReviewerSerializer(reviewer, application_course ->
    teacherapplication -> user/assigned_to/highschool, course, highschool,
    starting_academic_year)."""
    prefix = 'application_course__'
    return records.select_related(
        'reviewer',
        prefix + 'teacherapplication__user',
        prefix + 'teacherapplication__assigned_to',
        prefix + 'teacherapplication__highschool__district',
        prefix + 'highschool__district',
        prefix + 'starting_academic_year',
        *course_select_related(prefix + 'course__'),
    ).prefetch_related(
        *course_prefetch_related(prefix + 'course__')
    )


# --------------------------------------------------------------------------
# The student-backed side tables. StudentTuitionAssistanceSerializer,
# StudentSupportingDocumentSerializer, StudentAgreementSerializer and
# ParentConsentSerializer are all (student, term) and nothing else.
# --------------------------------------------------------------------------

def with_student_term_related(records):
    return records.select_related(
        *student_select_related('student__'),
        *term_select_related('term__'),
    )


def with_student_recommendation_related(records):
    """StudentRecommendationSerializer(student, term, submitted_by)."""
    return with_student_term_related(records).select_related('submitted_by')


def with_student_campus_id_related(records):
    """StudentCampusIDSerializer(student, campus)."""
    return records.select_related(
        *student_select_related('student__'), 'campus',
    ).prefetch_related(
        *campus_prefetch_related('campus__')
    )


def with_student_note_related(records):
    """StudentNoteSerializer(createdby, student).

    `student` is nullable here -- StudentNoteViewSet deliberately keeps
    null-student notes visible to every ce user -- which select_related
    handles as a LEFT JOIN, so no rows are dropped.
    """
    return records.select_related(
        'createdby', *student_select_related('student__'))


def with_course_administrator_related(records):
    """CourseAdministratorSerializer(course, user, faculty_id).

    `faculty_id` is a declared CharField backed by a property that reads
    `self.user.facultycoordinator.id` -- a reverse OneToOne, so a query per row
    without the join. It is included here rather than left as a marginal
    allowance because select_related reaches it: a LEFT JOIN, and the
    property's bare except still returns '' for a user with no coordinator
    record, now without a second query.
    """
    return records.select_related(
        'user', 'user__facultycoordinator',
        *course_select_related('course__'),
    ).prefetch_related(
        *course_prefetch_related('course__')
    )


# --------------------------------------------------------------------------
# Binding a plan to a viewset
# --------------------------------------------------------------------------

def eager_queryset(plan):
    """Class decorator: run ``get_queryset()``'s result through ``plan``.

    Wrapping the method rather than each ``return`` keeps the plans out of
    branchy bodies and guarantees no path is missed -- ``ClassSectionViewSet``
    alone returns from seven places and ``RegistrationViewSet`` from six, so
    editing each site is how a branch silently keeps its N+1.

    An ``.objects.none()`` return passes through harmlessly: applying
    ``select_related`` to an empty queryset is a no-op.

    Note that ``DatatablesFilterBackend`` calls ``get_queryset()`` twice per
    request (once for ``recordsTotal``), so the wrapped method must stay cheap
    -- it only attaches relation plans, it does not evaluate anything.
    """
    def decorate(cls):
        original = cls.get_queryset

        def get_queryset(self):
            return plan(original(self))

        get_queryset.__doc__ = original.__doc__
        get_queryset.__name__ = 'get_queryset'
        cls.get_queryset = get_queryset
        return cls

    return decorate
