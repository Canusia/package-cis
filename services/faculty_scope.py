"""Which teachers a faculty user may see, by course and academic year.

A faculty member's instructor list has always been derived: every teacher
holding a TeacherCourseCertificate for any course they administer
(``cis/views/teacher.py``). Nothing in that chain knows about a year, and
nothing lets CE say "Dr. Smith is responsible for these three instructors this
year, not all eleven".

``visible_teachers`` adds that, per course, without changing anything for a
tenant that configures nothing: a course with no ``FacultyTeacherAssignment``
rows for (user, year) still yields the full certificate list, byte-for-byte the
derivation that exists today. Absence of rows is the fallback signal, so a
half-finished configuration over-shows rather than silently hiding instructors
with nothing on screen to explain why.

A plain service function rather than a ``Teacher`` manager method: ``Teacher``
has no custom manager today and this is not a good enough reason for it to get
one.
"""
from django.db.models import Exists, OuterRef, Q

from cis.models.course import CourseAdministrator
from cis.models.faculty import (
    FacultyCourseAssignment, FacultyTeacherAssignment, FacultyYearSetup,
)
from cis.models.section import ClassSection
from cis.models.teacher import Teacher, TeacherCourseCertificate
from cis.utils import active_academic_year


def _tenant_faculty_scope_override(name):
    """Return the tenant's override for a faculty-scope rule, or None.

    Who a faculty member oversees is partly institutional policy, so the rule
    below is a default a tenant may replace by defining the same name in its
    ``services/faculty_scope.py``. Tenants that define nothing are unaffected.

    Imported inside the function on purpose -- a tenant's services module
    imports ``cis.models.*`` at its own module level, so resolving it at import
    time would risk AppRegistryNotReady. Same shape as
    ``cis/models/section.py::_tenant_registration_override``.
    """
    from cis.services.tenant_services import get_tenant_override
    return get_tenant_override('faculty_scope', name)


def default_visible_teachers(user, academic_year=None):
    """The cis default rule. Tenant modules re-export *this* name.

    For every course the user actively oversees: the assigned teachers if
    (user, course, year) is configured, otherwise every teacher certified for
    that course.

    Derived from the pair rule (``visible_pairs_q``, which a tenant may
    override) rather than restating it, so My Instructors, sections, rosters
    and the course columns cannot disagree (package-cis#108). A teacher is
    visible when any of their certificates is a visible pair; the pair rule
    requires an active-status one, so an instructor whose certificates are
    all Inactive, Applicant or Do Not Contact -- or gone -- is hidden even if
    CE assigned them (package-cis#107). One query with subqueries, never a
    loop over courses.
    """
    if academic_year is None:
        academic_year = active_academic_year()

    # Narrowed to the overseen courses first, so the pair rule's correlated
    # subqueries run over this mentor's rows, not the tenant's whole table.
    # The pair rule requires an overseen course anyway, so this changes cost,
    # not results.
    overseen = CourseAdministrator.objects.filter(
        user=user, status__iexact='active').values('course_id')

    by_certificate = TeacherCourseCertificate.objects.filter(
        course_id__in=overseen,
    ).filter(visible_pairs_q(
        user, course_field='course_id',
        teacher_field='teacher_highschool__teacher_id',
        academic_year=academic_year,
    )).values('teacher_highschool__teacher_id')

    return Teacher.objects.filter(id__in=by_certificate)


def visible_teachers(user, academic_year=None):
    """Teachers this faculty user may see, falling back per course.

    The public entrypoint every caller uses. Resolves the tenant seam first,
    then runs the cis default.
    """
    override = _tenant_faculty_scope_override('visible_teachers')
    # `is not visible_teachers` guards the re-export footgun: a tenant module
    # whose faculty_scope.py does `from cis.services.faculty_scope import
    # visible_teachers` would otherwise resolve to this very function and
    # recurse until the stack blows. Re-exporting default_visible_teachers is
    # the intended shape; this makes the other one merely redundant.
    if override is not None and override is not visible_teachers:
        return override(user, academic_year=academic_year)
    return default_visible_teachers(user, academic_year=academic_year)


def configured_course_ids(user, academic_year):
    """Course ids `user` has configured for `academic_year` (values queryset).

    A course is configured when it has FacultyTeacherAssignment rows, or a
    FacultyCourseAssignment row (which may stand alone: "no instructors"). The
    first half keeps assignments saved before FacultyCourseAssignment existed.
    """
    from cis.models.course import Course
    return Course.objects.filter(
        Q(id__in=FacultyCourseAssignment.objects.filter(
            user=user, academic_year=academic_year).values('course_id'))
        | Q(id__in=FacultyTeacherAssignment.objects.filter(
            user=user, academic_year=academic_year).values('course_id'))
    ).values('id')


_ANY_YEAR = object()


def _set_up_q(user, academic_year=_ANY_YEAR):
    """Exists() for "CE has set `user` up" -- for `academic_year` (a value or
    an OuterRef; None matches nothing), or for any year when omitted.

    A FacultyYearSetup marker, or any course/assignment row (data saved before
    the marker existed).
    """
    year = {} if academic_year is _ANY_YEAR else {'academic_year': academic_year}
    return (Exists(FacultyYearSetup.objects.filter(user=user, **year))
            | Exists(FacultyCourseAssignment.objects.filter(user=user, **year))
            | Exists(FacultyTeacherAssignment.objects.filter(user=user, **year)))


def is_set_up(user, academic_year=_ANY_YEAR):
    """True when `user` is set up for `academic_year` (any year when omitted)."""
    from cis.models.customuser import CustomUser
    return CustomUser.objects.filter(pk=user.pk).filter(
        _set_up_q(user, academic_year)).exists()


def visible_pairs_q(user, *, course_field, teacher_field, year_field=None,
                    academic_year=None, require_certificate=True):
    """A Q that keeps rows whose (course, teacher) pair `user` may see.

    The public entrypoint, and the tenant seam every faculty scope goes
    through: ``visible_teachers`` and ``visible_course_teachers`` are both
    derived from it. A tenant overrides ``visible_pairs_q`` (re-exporting
    ``default_visible_pairs_q`` for the cases it keeps) with the same
    signature; see ``default_visible_pairs_q`` for the rule.
    """
    override = _tenant_faculty_scope_override('visible_pairs_q')
    # Same re-export guard as visible_teachers.
    if override is not None and override is not visible_pairs_q:
        return override(
            user, course_field=course_field, teacher_field=teacher_field,
            year_field=year_field, academic_year=academic_year,
            require_certificate=require_certificate)
    return default_visible_pairs_q(
        user, course_field=course_field, teacher_field=teacher_field,
        year_field=year_field, academic_year=academic_year,
        require_certificate=require_certificate)


def default_visible_pairs_q(user, *, course_field, teacher_field, year_field=None,
                            academic_year=None, require_certificate=True):
    """The cis default pair rule. Tenant modules re-export *this* name.

    For any queryset whose rows carry a course and a teacher -- class sections,
    course certificates. The pair is visible when the user actively oversees
    the course and either:

    - the course is configured for the year and the teacher is assigned to it, or
    - the course is not configured for the year (the fallback),

    provided the year is set up for the user -- or the user has never been
    set up for any year, which keeps tenants that do not use assignments on
    the fallback. A mentor set up before but not for this year sees nothing
    until CE saves or copies it (package-faculty#3, FacultyYearSetup);

    and -- when `require_certificate` -- the teacher holds a certificate for
    the course in an active status (TeacherCourseCertificate.ACTIVE_STATUSES,
    compared case-insensitively). Non-active instructors are hidden from the
    mentor whether assigned or not (package-cis#107). Sections pass
    `require_certificate=False`: they keep showing assigned and fallback
    sections whatever the instructor's certificate.

    The year is `academic_year`, else the active year. `year_field` (e.g.
    'term__academic_year') judges each row against its own year instead; the
    faculty portal stopped passing it in package-faculty v0.0.4 (#3), and it
    stays in the signature because v0.0.3 still does -- a tenant override
    must accept and forward it. Correlated EXISTS subqueries, so it
    stays one query however many courses are overseen.
    """
    year = OuterRef(year_field) if year_field else (
        academic_year if academic_year is not None else active_academic_year())
    course = OuterRef(course_field)
    teacher = OuterRef(teacher_field)

    overseen = Exists(CourseAdministrator.objects.filter(
        user=user, status__iexact='active', course_id=course))
    assigned = Exists(FacultyTeacherAssignment.objects.filter(
        user=user, course_id=course, teacher_id=teacher, academic_year=year))
    configured = (
        Exists(FacultyCourseAssignment.objects.filter(
            user=user, course_id=course, academic_year=year))
        | Exists(FacultyTeacherAssignment.objects.filter(
            user=user, course_id=course, academic_year=year)))
    visible = (assigned | ~configured) & (_set_up_q(user, year) | ~_set_up_q(user))
    if require_certificate:
        visible &= Exists(TeacherCourseCertificate.objects.filter(
            active_certificate_q(),
            course_id=course, teacher_highschool__teacher_id=teacher))

    return overseen & visible


def visible_class_sections(user, academic_year=None):
    """Class sections `user` may see as a faculty member (package-cis#114 item 8).

    Sections of the courses they actively oversee, narrowed to their
    (course, instructor) pairs by ``visible_pairs_q`` -- ported from nnu's
    ``faculty.views.utils.overseen_class_sections``. Every section, whatever
    its term, is judged against one year's setup (`academic_year`, else the
    active year), the same year My Instructors uses. `require_certificate` is
    off: a course not configured for the year keeps every section, staffed
    or not.

    Returns a ClassSection queryset; callers filter with
    ``class_section__in=`` or ``id__in=...values('id')``.
    """
    return ClassSection.objects.filter(visible_pairs_q(
        user, course_field='course_id', teacher_field='teacher_id',
        academic_year=academic_year, require_certificate=False))


def visible_course_ids(user):
    """Ids of the courses `user` actively administers (values queryset).

    The course scope for faculty on endpoints whose rows carry a course but
    no instructor -- courses, course administrators, teacher applications.
    """
    return CourseAdministrator.objects.filter(
        user=user, status__iexact='active',
    ).exclude(course__isnull=True).values('course_id')


def section_scope_applies(user):
    """True when ClassSectionViewSet narrows `user`'s sections.

    Rollout gate (package-cis#114 item 8): before the faculty scope existed a
    faculty caller with no teacher_id got every section, and nothing told CE
    to set mentors up first. So the narrowing starts once CE has set this
    user up for any academic year (``is_set_up``: a FacultyYearSetup marker
    or assignment rows); until then the section feed keeps its old
    behaviour. Any year, not just the active one: a mentor set up last year
    and not yet this year sees what My Instructors shows (nothing), not
    every section. Every other faculty-scoped endpoint narrows
    unconditionally.
    """
    return is_set_up(user)


def active_certificate_q(prefix=''):
    """Q for a TeacherCourseCertificate in an active status (case-insensitive).

    `prefix` reaches the certificate through a relation, e.g.
    'teachercoursecertificate__'.
    """
    q = Q()
    for status in TeacherCourseCertificate.ACTIVE_STATUSES:
        q |= Q(**{f'{prefix}status__iexact': status})
    return q


def visible_course_teachers(user, academic_year=None):
    """{(course_id, teacher_id)} the user may see for one year.

    Built from course certificates, so it is the pairs a picker or a "courses"
    column can show. Use visible_pairs_q() to filter sections directly.
    """
    return set(TeacherCourseCertificate.objects.filter(visible_pairs_q(
        user, course_field='course_id',
        teacher_field='teacher_highschool__teacher_id',
        academic_year=academic_year,
    )).values_list('course_id', 'teacher_highschool__teacher_id'))
