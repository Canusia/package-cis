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
from django.db.models import Q

from cis.models.course import CourseAdministrator
from cis.models.faculty import FacultyTeacherAssignment
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
    (user, course, year) has assignment rows, otherwise every teacher certified
    for that course.

    Two subqueries and a union, never a loop over courses, so the cost is one
    round trip whether the faculty member oversees one course or fifty.
    """
    if academic_year is None:
        academic_year = active_academic_year()

    overseen_courses = CourseAdministrator.objects.filter(
        user=user, status__iexact='active'
    ).values('course_id')

    assignments = FacultyTeacherAssignment.objects.filter(
        user=user,
        academic_year=academic_year,
        course_id__in=overseen_courses,
    )

    # Courses this faculty member has configured for this year. Their teacher
    # list is exactly what was picked; every other overseen course falls back.
    configured_courses = assignments.values('course_id')

    assigned_teachers = assignments.values('teacher_id')

    # The pre-existing derivation, unchanged, minus the configured courses.
    fallback_teachers = TeacherCourseCertificate.objects.filter(
        course_id__in=overseen_courses,
    ).exclude(
        course_id__in=configured_courses,
    ).values('teacher_highschool__teacher_id')

    return Teacher.objects.filter(
        Q(id__in=assigned_teachers) | Q(id__in=fallback_teachers)
    )


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
