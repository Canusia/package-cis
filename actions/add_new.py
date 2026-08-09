"""
Actions behind /ce/add_new_ajax/ (cis.views.ajax.add_new).

Each entry is a thin wrapper over the handler that the old `if model == '…'`
chain called, and its `permission` is the authorization that chain mostly did
not have. The slug must match the `model` value the client posts.

Two entry points reach this registry and neither gates by role on its own:

  * /ce/add_new_ajax/          — no role guard on the URL
  * /highschool_admin/ajax/    — confirms the caller is an HS admin, but not
                                 which models they may act on

LoginRequiredMiddleware means the floor is "any authenticated user", which
includes students, applicants and instructors. So the permission declared here
is the only thing standing in front of each handler, and
GuardedActionRegistry refuses to register an action that omits one.

Notes actions (`*note` slugs) still dispatch from the if-chain in views/ajax.py;
they move here in a follow-up.
"""
from django.http import JsonResponse

from cis.actions.registry import add_new_actions

from cis.utils import user_has_cis_role, user_has_highschool_admin_role

GROUP = 'add_new'


def _cis_only(user):
    return user_has_cis_role(user)


def _cis_or_hs_admin(user):
    return user_has_cis_role(user) or user_has_highschool_admin_role(user)


def _denied(message='You are not authorized to perform this action.'):
    return JsonResponse({'status': 'error', 'message': message}, status=403)


def _register(slug, label, permission=_cis_only):
    """Register `slug` as an action delegating to a handler of the same name."""
    def decorator(fn):
        return add_new_actions.action(
            GROUP, label=label, scope=['detail'], slug=slug,
            permission=permission,
        )(fn)
    return decorator


# ---------------------------------------------------------------------------
# District
# ---------------------------------------------------------------------------

@_register('district', 'Add/Edit District')
def district(request):
    from cis.views.district import add_new
    return add_new(request)


@_register('districtadministratorrole', 'Add District Administrator Position')
def districtadministratorrole(request):
    # PT-41: renders DistrictAdministratorPositionForm, whose `district` field
    # discloses every district name + UUID, and creates a
    # DistrictAdministratorPosition on POST. Guard covers GET and POST.
    from cis.views.district_administrator import add_new_role
    return add_new_role(request)


# ---------------------------------------------------------------------------
# High school / personnel
# ---------------------------------------------------------------------------

@_register('hsadministratorrole', 'Add HS Administrator Position',
           permission=_cis_or_hs_admin)
def hsadministratorrole(request):
    """
    The one add_new action the HS admin portal uses (personnel.js "Update
    Status"). CE keeps unrestricted access; an HS admin may only touch a
    position at a school they administer.

    The handler itself has no object scoping — its only reference to
    user_has_cis_role blanks `record` before render, which is a display
    nicety, not a gate — so the scoping lives here.
    """
    from cis.views.hs_administrator import add_new_role

    if not user_has_cis_role(request.user):
        if not _hs_admin_may_touch_position(request):
            return _denied('You are not authorized to manage this high school.')

    return add_new_role(request)


def _hs_admin_may_touch_position(request):
    """
    True when every high school this request refers to is one the caller
    administers. Checks the posted `highschool`, and the school on the
    existing position when an `id` is supplied, so neither the create nor the
    edit path can reach across schools.
    """
    from cis.models.highschool_administrator import (
        HSAdministrator, HSAdministratorPosition,
    )

    try:
        hsadmin = HSAdministrator.objects.get(user__id=request.user.id)
    except HSAdministrator.DoesNotExist:
        return False

    allowed = set(str(pk) for pk in hsadmin.get_highschools().values_list('id', flat=True))
    if not allowed:
        return False

    source = request.POST if request.method == 'POST' else request.GET

    posted_highschool = source.get('highschool')
    if posted_highschool and str(posted_highschool) not in allowed:
        return False

    record_id = source.get('id', '-1')
    if record_id and str(record_id) != '-1':
        try:
            record = HSAdministratorPosition.objects.get(pk=record_id)
        except (HSAdministratorPosition.DoesNotExist, ValueError, TypeError):
            return False
        if str(record.highschool_id) not in allowed:
            return False

    return True


@_register('highschoolcollegeadvisor', 'Add College Advisor')
def highschoolcollegeadvisor(request):
    from cis.views.highschool import add_new_college_advisor
    return add_new_college_advisor(request)


# ---------------------------------------------------------------------------
# Teacher
# ---------------------------------------------------------------------------

@_register('teacherhighschool', 'Add Teacher High School')
def teacherhighschool(request):
    # PT-8: TeacherHighSchool.save() also elevates the teacher into the
    # 'instructor' group, so this is CE-only. Guard covers GET and POST.
    from cis.views.teacher import add_new_highschool
    return add_new_highschool(request)


@_register('teachercoursecertificate', 'Add Course Certificate')
def teachercoursecertificate(request):
    from cis.views.teacher import add_new_course_certificate
    return add_new_course_certificate(request)


@_register('delete_teacher_upload', 'Delete Teacher Upload')
def delete_teacher_upload(request):
    # Deletes a TeacherUpload by UUID straight from the query string, with no
    # ownership check in the handler. add_new_ajax is its only entry point.
    from cis.views.teacher import delete_teacher_upload as handler
    return handler(request)


# ---------------------------------------------------------------------------
# Course / faculty
# ---------------------------------------------------------------------------

@_register('course_administrator', 'Manage Course Administrator')
def course_administrator(request):
    from cis.views.course import manage_course_administrator_role
    return manage_course_administrator_role(request)


@_register('delete_course_upload', 'Delete Course Upload')
def delete_course_upload(request):
    # Same shape as delete_teacher_upload.
    from cis.views.course import delete_course_upload as handler
    return handler(request)


@_register('faculty_course_administrator', 'Add Faculty Course')
def faculty_course_administrator(request):
    from cis.views.faculty import add_new_course
    return add_new_course(request)


@_register('facultycoursecoordinator', 'Add Faculty Course Coordinator')
def facultycoursecoordinator(request):
    # Distinct slug, same handler as faculty_course_administrator.
    from cis.views.faculty import add_new_course
    return add_new_course(request)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

@_register('classsection', 'Edit Class Section')
def classsection(request):
    from cis.views.section import edit_record
    return edit_record(request)


@_register('courseoffering', 'Manage Course Offering')
def courseoffering(request):
    from cis.views.section import manage_courseoffering
    return manage_courseoffering(request)


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

@_register('student', 'Edit Student')
def student(request):
    from cis.views.student import edit_record
    return edit_record(request)


@_register('studentcampusid', 'Edit Student Campus ID')
def studentcampusid(request):
    from cis.views.student import edit_campus_id
    return edit_campus_id(request)


@_register('studentregistration', 'Manage Registration')
def studentregistration(request):
    from cis.views.registration import manage_registration
    return manage_registration(request)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@_register('eventspeaker', 'Add Event Speaker')
def eventspeaker(request):
    from cis.views.event import add_new_speaker
    return add_new_speaker(request)


@_register('eventcohort', 'Add Event Cohort')
def eventcohort(request):
    from cis.views.event import add_new_cohort
    return add_new_cohort(request)


# ---------------------------------------------------------------------------
# Applications / support
# ---------------------------------------------------------------------------

@_register('applicationcoursereviewer', 'Add Application Course Reviewer')
def applicationcoursereviewer(request):
    from cis.views.teacher_application import add_new_course_reviewer
    return add_new_course_reviewer(request)


@_register('supportrequest', 'Add Support Request')
def supportrequest(request):
    # Documented as "Add support request for CE Staff" in support_ticket, which
    # has no check of its own; gated here to match the docstring.
    from support_ticket.views.tickets import add_new_support_request
    return add_new_support_request(request)
