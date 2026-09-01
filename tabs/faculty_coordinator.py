"""FacultyCoordinator detail-page tab content functions (see cis/tabs/course.py).
Eager-imported by myce/component_registry/faculty_coordinator.py so decorators run.
"""
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from cis.utils import active_academic_year
from myce.component_registry.faculty_coordinator import faculty_coordinator_tabs  # noqa: F401


@faculty_coordinator_tabs.tab(slug='courses', title='Course(s)', order=10,
                              template='cis/faculty/tabs/_courses.html',
                              active=True)
def courses_tab(request, record):
    """CourseAdministrator rows for this coordinator only, via the shared
    faculty_coords_table service's 'faculty_coords_detail' variant -- the
    same row shape and bulk actions (Change Status, Delete) as the By Course
    tab on /ce/faculty_coordinators/, scoped with the same
    faculty_coordinator_user_id param that tab's api already supports
    (cis/views/faculty.py's CourseAdministratorViewSet.get_queryset).

    No mark_safe needed here: the api_url is embedded via json.dumps into
    opts_json and output with |safe by the partial, not interpolated
    directly into a JS string literal -- json.dumps does not HTML-escape
    '&', so it survives Django autoescaping without help.
    """
    from cis.services.table_configs import get_table_config

    build = get_table_config('faculty_coords_table').build_config
    api_url = (
        '/ce/api/course_administrator?format=datatables'
        f'&faculty_coordinator_user_id={record.user.id}')

    return {
        'course_administrator_table': build(
            variant='faculty_coords_detail',
            api_url=api_url,
            parent_id=str(record.id),
            bulk_actions={
                'change_course_administrator_status': {
                    'label': 'Change Status',
                    'icon': 'fas fa-edit',
                    'btn_class': 'btn-primary',
                    'confirm': None,
                },
                'delete_course_administrator': {
                    'label': 'Delete',
                    'icon': 'fas fa-trash',
                    'btn_class': 'btn-danger',
                    'method': 'POST',
                    'confirm': (
                        'Delete the selected course assignment(s)? '
                        'The faculty coordinator record and the user '
                        'account are NOT deleted.'
                    ),
                },
            },
            bulk_actions_url=reverse('cis:faculty_bulk_actions'),
        ),
    }


# --------------------------------------------------------------------------
# Assigned Instructor(s)
#
# The only screen that writes cis.FacultyTeacherAssignment. Everything it shows
# is derived from the same chain cis/services/faculty_scope.py reads --
# CourseAdministrator(status__iexact='active') for the courses, and
# TeacherCourseCertificate for who may be picked -- so the admin screen and the
# enforcement rule cannot drift apart.
# --------------------------------------------------------------------------

ASSIGNED_INSTRUCTORS_SLUG = 'assigned_instructors'


def _overseen_courses(user):
    """Courses this faculty user actively oversees.

    Deliberately the same expression as
    faculty_scope.default_visible_teachers: CourseAdministrator rows with
    status iexact 'active'. If this screen and that rule ever derived the set
    differently, CE would be configuring courses the rule ignores.
    """
    from cis.models.course import Course, CourseAdministrator
    return Course.objects.filter(
        id__in=CourseAdministrator.objects.filter(
            user=user, status__iexact='active'
        ).values('course_id')
    ).order_by('catalog_number', 'title')


def _certified_teachers(courses):
    """{course_id: [Teacher, ...]} for the courses given, in one round trip."""
    from cis.models.teacher import Teacher, TeacherCourseCertificate

    pairs = set(TeacherCourseCertificate.objects.filter(
        course__in=courses
    ).values_list('course_id', 'teacher_highschool__teacher_id'))

    teachers = {
        t.id: t for t in Teacher.objects.filter(
            id__in={tid for _, tid in pairs}).select_related('user')
    }
    by_course = defaultdict(list)
    for course_id, teacher_id in pairs:
        teacher = teachers.get(teacher_id)
        if teacher is not None:
            by_course[course_id].append(teacher)
    for course_id in by_course:
        by_course[course_id].sort(key=str)
    return by_course


def _academic_year(request, param='academic_year'):
    """The year the tab is operating on: the submitted one, else the active one.

    The selector round-trips through this single parameter, in POST as well as
    GET, so a save or a copy stays on the year the user was looking at.
    """
    from cis.models.term import AcademicYear
    raw = request.POST.get(param) or request.GET.get(param)
    if raw:
        try:
            return AcademicYear.objects.filter(pk=raw).first()
        except (ValueError, ValidationError):
            return None
    return active_academic_year()


def _save_assignments(request, faculty_user, academic_year, courses, certified):
    """Make the rows match the submission, for the submitted courses only.

    Only courses listed in the hidden `course` inputs are touched. That is what
    separates "the picker was cleared" (course submitted, no teachers -> rows
    deleted, the course falls back to All instructors) from "this course was
    never on the form" (left exactly as it was) -- a browser omits an empty
    multi-select entirely, so the two are otherwise indistinguishable.

    Courses the faculty member does not actively oversee, and teachers not
    certified for the course, are dropped rather than trusted: this POST is
    user input, and the picker's own limits are not a security boundary.
    """
    from cis.models.faculty import FacultyTeacherAssignment

    by_id = {str(c.id): c for c in courses}
    for raw_course_id in request.POST.getlist('course'):
        course = by_id.get(raw_course_id)
        if course is None:
            continue

        allowed = {str(t.id) for t in certified.get(course.id, [])}
        wanted = {
            t for t in request.POST.getlist(f'teachers_{course.id}')
            if t in allowed
        }

        existing = {
            str(row.teacher_id): row
            for row in FacultyTeacherAssignment.objects.filter(
                user=faculty_user, course=course, academic_year=academic_year)
        }

        for teacher_id in existing.keys() - wanted:
            existing[teacher_id].delete()

        for teacher_id in wanted - existing.keys():
            try:
                with transaction.atomic():
                    FacultyTeacherAssignment.objects.create(
                        user=faculty_user, course=course,
                        teacher_id=teacher_id, academic_year=academic_year,
                        created_by=request.user)
            except IntegrityError:
                # Someone else saved the same row between the read above and
                # this write. The row exists, which is all that was wanted.
                pass


def _copy_assignments(request, faculty_user, source_year, target_year):
    """Clone one year's rows onto another, for this faculty member only.

    Returns the number of rows created. Rows that already exist are skipped
    rather than allowed to raise: unique_together is
    (user, course, teacher, academic_year), so a second copy of the same year
    would otherwise be an IntegrityError instead of a no-op. `created_by` is
    the person clicking copy, not the original assigner -- this is a new
    decision made today.
    """
    from cis.models.faculty import FacultyTeacherAssignment

    if source_year is None or target_year is None or source_year == target_year:
        return 0

    created = 0
    rows = FacultyTeacherAssignment.objects.filter(
        user=faculty_user, academic_year=source_year)
    for row in rows:
        try:
            with transaction.atomic():
                _, was_created = FacultyTeacherAssignment.objects.get_or_create(
                    user=faculty_user, course_id=row.course_id,
                    teacher_id=row.teacher_id, academic_year=target_year,
                    defaults={'created_by': request.user})
        except IntegrityError:
            continue
        created += int(was_created)
    return created


@faculty_coordinator_tabs.tab(slug=ASSIGNED_INSTRUCTORS_SLUG,
                              title='Assigned Instructor(s)', order=15,
                              template='cis/faculty/tabs/_assigned_instructors.html')
def assigned_instructors_tab(request, record):
    from cis.models.faculty import FacultyTeacherAssignment
    from cis.models.term import AcademicYear

    faculty_user = record.user
    academic_year = _academic_year(request)
    courses = list(_overseen_courses(faculty_user))
    certified = _certified_teachers(courses)

    message = None
    if request.method == 'POST' and academic_year is not None:
        action = request.POST.get('action')
        if action == 'save_assigned_instructors':
            _save_assignments(
                request, faculty_user, academic_year, courses, certified)
            message = 'Assignments saved.'
        elif action == 'copy_assigned_instructors':
            source = _academic_year(request, 'source_academic_year')
            created = _copy_assignments(
                request, faculty_user, source, academic_year)
            message = (
                f'Copied {created} assignment(s) from {source}.'
                if created else
                f'Nothing to copy from {source}.')

    assigned = defaultdict(set)
    if academic_year is not None:
        for course_id, teacher_id in FacultyTeacherAssignment.objects.filter(
            user=faculty_user, academic_year=academic_year, course__in=courses
        ).values_list('course_id', 'teacher_id'):
            assigned[course_id].add(str(teacher_id))

    rows = [{
        'course': course,
        'teachers': certified.get(course.id, []),
        'selected': assigned.get(course.id, set()),
        # The fallback is a state the page states in words. An empty picker on
        # its own would leave the reader to infer it, and the two readings --
        # "nobody" and "everybody" -- are opposites.
        'unassigned': not assigned.get(course.id),
    } for course in courses]

    # The faculty portal resolves through active_academic_year(), so
    # assignments saved against any other year are a silent no-op today. The
    # fallback over-shows by design, which means that no-op is invisible: a full
    # instructor list reads the same whether the year is unconfigured or
    # configured in the wrong year. QA hit exactly this within minutes, so the
    # page names the active year rather than leaving it to be inferred.
    active_year = active_academic_year()

    return {
        'rows': rows,
        'academic_year': academic_year,
        'academic_years': AcademicYear.objects.all().order_by('-name'),
        'active_year': active_year,
        'editing_inactive_year': (
            academic_year is not None
            and active_year is not None
            and academic_year != active_year
        ),
        'tab_url': reverse('cis:faculty_coordinator_tab',
                           args=[record.id, ASSIGNED_INSTRUCTORS_SLUG]),
        'message': message,
    }


@faculty_coordinator_tabs.tab(slug='class_sections', title='Class Sections',
                              order=20,
                              template='cis/faculty/tabs/_class_sections.html')
def class_sections_tab(request, record):
    from cis.models.term import Term
    from cis.services.table_configs import get_table_config

    build = get_table_config('sections_table').build_config
    # No mark_safe needed: this URL is consumed via the table config's
    # opts_json|safe, not interpolated into a JS string by the fragment.
    api_url = (
        f'/ce/api/class_section/?course_administrator_user_id={record.user.id}'
        '&term=-1&format=datatables')
    return {
        'sections_table': build(
            variant='faculty_coordinator_detail',
            api_url=api_url,
            filter_form_selector='#fc_class_section_filter',
        ),
        # Opens on "All Terms" (term=-1), matching EWU's sibling sections tabs
        # (cis/tabs/highschool.py, course.py, teacher.py). The user narrows via
        # the dropdown.
        'terms': Term.objects.all().order_by('-code'),
    }


@faculty_coordinator_tabs.tab(slug='visits', title='Visit(s)', order=30,
                              template='cis/faculty/tabs/_visits.html')
def visits_tab(request, record):
    return {}
