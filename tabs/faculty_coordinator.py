"""FacultyCoordinator detail-page tab content functions (see cis/tabs/course.py).
Eager-imported by myce/component_registry/faculty_coordinator.py so decorators run.
"""
import copy
from cis.campus_context import campus_terms
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
    """{course_id: [Teacher, ...]} for the courses given, in one round trip.

    Each Teacher carries, per course (one Teacher object per (course,
    teacher)):

    - `cert_inactive`: True unless at least one of the teacher's certificates
      for the course is in an active status
      (TeacherCourseCertificate.ACTIVE_STATUSES). An allow-list, so Applicant
      and Do Not Contact count as not active alongside Inactive
      (package-cis#107); the badge and the certificate filter read it
      (package-faculty#2 D2).
    - `cert_status`: the statuses to put on that badge, e.g. "Do Not Contact".
    """
    from cis.models.teacher import Teacher, TeacherCourseCertificate

    active = {s.lower() for s in TeacherCourseCertificate.ACTIVE_STATUSES}
    # {(course, teacher): {lowercased status: display form}}, so statuses
    # differing only in case are one badge entry.
    statuses = defaultdict(dict)
    for course_id, teacher_id, status in TeacherCourseCertificate.objects.filter(
        course__in=courses
    ).values_list('course_id', 'teacher_highschool__teacher_id', 'status'):
        status = (status or '').strip()
        statuses[(course_id, teacher_id)].setdefault(status.lower(), status)

    teachers = {
        t.id: t for t in Teacher.objects.filter(
            id__in={tid for _, tid in statuses}).select_related('user')
    }
    by_course = defaultdict(list)
    for (course_id, teacher_id), course_statuses in statuses.items():
        base = teachers.get(teacher_id)
        if base is None:
            continue
        teacher = copy.copy(base)
        teacher.cert_inactive = not (course_statuses.keys() & active)
        teacher.cert_status = (
            ', '.join(sorted(s or 'No status' for s in course_statuses.values()))
            if teacher.cert_inactive else '')
        by_course[course_id].append(teacher)
    for course_id in by_course:
        by_course[course_id].sort(key=str)
    return by_course


CERT_FILTERS = (('active', 'Active only'), ('all', 'All'))
MODES = ('all', 'selected', 'none')


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


def _configured(faculty_user, academic_year, courses):
    """Ids of `courses` configured for `academic_year`, in one query.

    The same test as faculty_scope.configured_course_ids (which it calls), so
    the screen, the save and the enforcement rule agree (package-cis#109).
    """
    from cis.services.faculty_scope import configured_course_ids
    return set(configured_course_ids(faculty_user, academic_year).filter(
        id__in=[c.id for c in courses]).values_list('id', flat=True))


def _save_assignments(request, faculty_user, academic_year, courses, certified,
                      listed):
    """Make the rows match the submission, for the submitted courses only.

    Only courses listed in the hidden `course` inputs are touched. That is what
    separates "nothing was ticked" from "this course was never on the form"
    (left exactly as it was) -- a browser omits unticked checkboxes entirely.

    Each course posts `mode_<course id>` (package-faculty#2):

    - `all`: no configuration -- every certified instructor (rows deleted).
    - `selected`: exactly the ticked `teachers_<course id>`; none ticked = none.
    - `none`: configured with no instructors.

    Without a mode (an older form), ticked teachers mean `selected` and none
    means `all`, as before.

    The By instructor view posts `pair` values ("<course id>:<teacher id>")
    instead, and renders an unconfigured course with every listed instructor
    ticked -- the mentor sees them all (package-cis#106). So, per course:

    - `reset_all` lists it: `all`, whatever is ticked.
    - unconfigured, and every listed instructor still ticked: stays `all`.
    - otherwise the ticks are the selection: some ticked = `selected`, none =
      `none`.

    The form posts what it showed: a `shown` "<course id>:<teacher id>" per
    listed instructor, and `was_all` per course that was on All. Those, not
    today's data, decide "every listed instructor still ticked", so an
    instructor certified (or a course configured) between render and save
    cannot flip a course CE left alone. `listed` -- {course id: {teacher id}}
    recomputed now -- covers a form that predates those inputs.

    Courses the faculty member does not actively oversee, and teachers not
    certified for the course, are dropped rather than trusted: this POST is
    user input, and the form's own limits are not a security boundary.
    """
    from cis.models.faculty import (
        FacultyCourseAssignment, FacultyTeacherAssignment, FacultyYearSetup,
    )

    # Any save sets the year up, even one leaving every course on All -- that
    # is how CE turns a not-yet-set-up year back on (package-faculty#3).
    _mark_set_up(FacultyYearSetup, request, faculty_user, academic_year)

    by_instructor = request.POST.get('view') == 'instructor'
    pairs = defaultdict(set)
    for raw in request.POST.getlist('pair'):
        course_id, _, teacher_id = raw.partition(':')
        pairs[course_id].add(teacher_id)
    reset_all = set(request.POST.getlist('reset_all'))
    if 'shown' in request.POST or 'was_all' in request.POST:
        listed = defaultdict(set)
        for raw in request.POST.getlist('shown'):
            course_id, _, teacher_id = raw.partition(':')
            listed[course_id].add(teacher_id)
        was_all = set(request.POST.getlist('was_all'))
    else:
        listed = {str(k): v for k, v in listed.items()}
        was_all = None

    # Read the year's rows once, not per course (package-cis#109).
    configured_ids = _configured(faculty_user, academic_year, courses)
    setting_ids = set(FacultyCourseAssignment.objects.filter(
        user=faculty_user, academic_year=academic_year, course__in=courses,
    ).values_list('course_id', flat=True))
    existing_rows = defaultdict(dict)
    for row in FacultyTeacherAssignment.objects.filter(
            user=faculty_user, academic_year=academic_year, course__in=courses):
        existing_rows[row.course_id][str(row.teacher_id)] = row

    by_id = {str(c.id): c for c in courses}
    # dict.fromkeys: a course posted twice is handled once, since the rows
    # above were read once.
    for raw_course_id in dict.fromkeys(request.POST.getlist('course')):
        course = by_id.get(raw_course_id)
        if course is None:
            continue

        allowed = {str(t.id) for t in certified.get(course.id, [])}
        configured = course.id in configured_ids

        if by_instructor:
            wanted = pairs.get(raw_course_id, set()) & allowed
            if raw_course_id in reset_all:
                mode = 'all'
            elif ((raw_course_id in was_all) if was_all is not None
                  else not configured) and wanted >= listed.get(raw_course_id, set()):
                mode = 'all'
            else:
                mode = 'selected' if wanted else 'none'
        else:
            wanted = {
                t for t in request.POST.getlist(f'teachers_{course.id}')
                if t in allowed
            }
            mode = request.POST.get(f'mode_{course.id}')
            if mode not in MODES:
                mode = 'selected' if wanted else 'all'
        if mode != 'selected':
            wanted = set()

        if mode == 'all':
            if course.id in setting_ids:
                FacultyCourseAssignment.objects.filter(
                    user=faculty_user, course=course,
                    academic_year=academic_year).delete()
        elif course.id not in setting_ids:
            try:
                with transaction.atomic():
                    FacultyCourseAssignment.objects.get_or_create(
                        user=faculty_user, course=course, academic_year=academic_year,
                        defaults={'created_by': request.user})
            except IntegrityError:
                pass

        existing = existing_rows[course.id]

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


def _mark_set_up(model, request, faculty_user, academic_year):
    """Write the FacultyYearSetup marker; True when it was created."""
    try:
        with transaction.atomic():
            _, created = model.objects.get_or_create(
                user=faculty_user, academic_year=academic_year,
                defaults={'created_by': request.user})
    except IntegrityError:
        return False
    return created


def _copy_assignments(request, faculty_user, source_year, target_year):
    """Clone one year's rows onto another, for this faculty member only.

    Returns (year set up, course settings created, assignments created): a
    "No instructors" course copies as a setting with no assignments, and a
    year with every course on All copies as the set-up marker alone -- CE
    must hear about both (package-cis#105, package-faculty#3). A source year
    that was never set up copies nothing. Rows that already exist are skipped
    rather than allowed to raise: unique_together is
    (user, course, teacher, academic_year), so a second copy of the same year
    would otherwise be an IntegrityError instead of a no-op. `created_by` is
    the person clicking copy, not the original assigner -- this is a new
    decision made today.
    """
    from cis.models.faculty import FacultyTeacherAssignment

    if source_year is None or target_year is None or source_year == target_year:
        return False, 0, 0

    from cis.models.faculty import FacultyCourseAssignment, FacultyYearSetup
    from cis.services.faculty_scope import is_set_up

    if not is_set_up(faculty_user, source_year):
        return False, 0, 0
    year_created = _mark_set_up(
        FacultyYearSetup, request, faculty_user, target_year)

    # Configuration rows first, so a "no instructors" course carries over too.
    settings_created = 0
    for course_id in FacultyCourseAssignment.objects.filter(
        user=faculty_user, academic_year=source_year
    ).values_list('course_id', flat=True):
        try:
            with transaction.atomic():
                _, was_created = FacultyCourseAssignment.objects.get_or_create(
                    user=faculty_user, course_id=course_id, academic_year=target_year,
                    defaults={'created_by': request.user})
        except IntegrityError:
            continue
        settings_created += int(was_created)

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
    return year_created, settings_created, created


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

    # Certificate filter (D2). An instructor already assigned is always listed,
    # badged, so a save under "Active only" never drops them unseen.
    cert_filter = request.POST.get('cert_status') or request.GET.get('cert_status')
    if cert_filter not in dict(CERT_FILTERS):
        cert_filter = 'active'

    def load_assigned():
        assigned = defaultdict(set)
        if academic_year is not None:
            for course_id, teacher_id in FacultyTeacherAssignment.objects.filter(
                user=faculty_user, academic_year=academic_year, course__in=courses
            ).values_list('course_id', 'teacher_id'):
                assigned[course_id].add(str(teacher_id))
        return assigned

    def listed(course, assigned):
        return [
            t for t in certified.get(course.id, [])
            if cert_filter == 'all' or not t.cert_inactive
            or str(t.id) in assigned.get(course.id, set())
        ]

    message = None
    if request.method == 'POST' and academic_year is not None:
        action = request.POST.get('action')
        if action == 'save_assigned_instructors':
            # What the submitted form listed, so the save can tell "left every
            # instructor ticked" from "narrowed the list" (package-cis#106).
            before = load_assigned()
            shown = {c.id: {str(t.id) for t in listed(c, before)} for c in courses}
            _save_assignments(
                request, faculty_user, academic_year, courses, certified, shown)
            message = 'Assignments saved.'
        elif action == 'copy_assigned_instructors':
            source = _academic_year(request, 'source_academic_year')
            year_created, settings_created, created = _copy_assignments(
                request, faculty_user, source, academic_year)
            if settings_created or created:
                message = (f'Copied {settings_created} course setting(s) and '
                           f'{created} assignment(s) from {source}.')
            elif year_created:
                message = (f'Copied {source}: every course on All certified '
                           'instructors.')
            else:
                message = f'Nothing to copy from {source}.'

    from cis.services.faculty_scope import is_set_up, visible_course_teachers

    assigned = load_assigned()
    configured = (
        _configured(faculty_user, academic_year, courses)
        if academic_year is not None else set())

    rows = []
    for course in courses:
        if course.id not in configured:
            mode = 'all'
        elif assigned.get(course.id):
            mode = 'selected'
        else:
            mode = 'none'
        rows.append({
            'course': course,
            'teachers': listed(course, assigned),
            'selected': assigned.get(course.id, set()),
            'mode': mode,
            # The fallback is a state the page states in words: "nobody" and
            # "everybody" are opposite readings of an empty list.
            'unassigned': mode == 'all',
        })

    # By instructor: one row per listed instructor, a checkbox per course.
    instructors = {}
    for row in rows:
        for teacher in row['teachers']:
            entry = instructors.setdefault(teacher.id, {'teacher': teacher, 'courses': []})
            entry['courses'].append({
                'course': row['course'],
                # An unconfigured course shows the mentor everyone, so it
                # renders ticked (package-cis#106).
                'checked': row['mode'] == 'all' or str(teacher.id) in row['selected'],
                'cert_inactive': teacher.cert_inactive,
                'cert_status': teacher.cert_status,
            })
    by_instructor = sorted(instructors.values(), key=lambda e: str(e['teacher']))

    # What the mentor ends up seeing for this year, to check against the source.
    summary = None
    if academic_year is not None:
        pairs = visible_course_teachers(faculty_user, academic_year)
        summary = {'instructors': len({t for _, t in pairs}),
                   'courses': len({c for c, _ in pairs})}

    # The faculty portal resolves through active_academic_year(), for the
    # instructor list and for sections of every term (package-faculty#3,
    # superseding #2's D1). The fallback over-shows by design, so a wrong-year
    # configuration is easy to miss -- QA hit exactly this within minutes, so
    # the page names the active year rather than leaving it to be inferred.
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
        # Set up for another year but not this one: the mentor sees nothing in
        # this year until CE saves or copies it (package-faculty#3).
        'year_not_set_up': (
            academic_year is not None
            and not is_set_up(faculty_user, academic_year)
            and is_set_up(faculty_user)),
        'cert_filter': cert_filter,
        'cert_filters': CERT_FILTERS,
        'by_instructor': by_instructor,
        'summary': summary,
        'faculty_user': faculty_user,
        'view': 'instructor' if (request.POST.get('view') or request.GET.get('view')) == 'instructor' else 'course',
    }


@faculty_coordinator_tabs.tab(slug='class_sections', title='Class Sections',
                              order=20,
                              template='cis/faculty/tabs/_class_sections.html')
def class_sections_tab(request, record):
    from cis.services.table_configs import get_table_config

    build = get_table_config('sections_table').build_config
    # No mark_safe needed: this URL is consumed via the table config's
    # opts_json|safe, not interpolated into a JS string by the fragment.
    api_url = (
        f'/ce/api/class_section/?course_administrator_user_id={record.user.id}'
        '&term=-1&include_sub_terms=1&format=datatables')
    return {
        'sections_table': build(
            variant='faculty_coordinator_detail',
            api_url=api_url,
            filter_form_selector='#fc_class_section_filter',
        ),
        # Opens on "All Terms" (term=-1), matching EWU's sibling sections tabs
        # (cis/tabs/highschool.py, course.py, teacher.py). The user narrows via
        # the dropdown.
        'terms': campus_terms().order_by('-code'),
    }


@faculty_coordinator_tabs.tab(slug='visits', title='Visit(s)', order=30,
                              template='cis/faculty/tabs/_visits.html')
def visits_tab(request, record):
    return {}
