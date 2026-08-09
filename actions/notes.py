"""
The note kinds cis owns, and their add_new actions.

Each kind is declared once as a NoteType and registered as an action on
add_new_actions, which replaces the note branches of the
`if model == '…'` chain in views/ajax.py.

Permissions come from evidence — which portal template or view actually posts
each slug — not from assumption. Where no poster could be found, today's
behaviour (any authenticated user) is preserved explicitly and flagged, rather
than tightened on a guess.

The GET path still renders through views/note.py::add_new_note, which builds a
per-kind title and menu; consolidating that rendering is a separate step.
"""
from django.http import JsonResponse

from cis.actions.registry import add_new_actions

from cis.notes import NoteType, note_types, _authenticated
from cis.utils import (
    user_has_cis_or_faculty_role,
    user_has_cis_role,
    user_has_highschool_admin_role,
    user_has_instructor_role,
    user_has_student_role,
)

GROUP = 'add_new_notes'


def _cis(user):
    return user_has_cis_role(user)


def _cis_or_instructor(user):
    return user_has_cis_role(user) or user_has_instructor_role(user)


def _cis_or_hs_admin(user):
    return user_has_cis_role(user) or user_has_highschool_admin_role(user)


def _ticket_participant(user):
    # support_ticket posts model=ticketnote from its student, instructor and
    # highschool_admin views as well as the CE one.
    return (
        user_has_cis_role(user)
        or user_has_student_role(user)
        or user_has_instructor_role(user)
        or user_has_highschool_admin_role(user)
    )


def _student_in_hs_admin_scope(user, student):
    """
    An HS admin may only reply against a student at one of their schools.

    The HS admin portal scopes note *reading* already; this write path had no
    scoping at all, so a reply could be posted against any student UUID.
    """
    if user_has_cis_role(user):
        return True

    from cis.models.highschool_administrator import HSAdministrator

    try:
        hsadmin = HSAdministrator.objects.get(user__id=user.id)
    except HSAdministrator.DoesNotExist:
        return False

    allowed = set(hsadmin.get_highschools().values_list('id', flat=True))
    if not allowed:
        return False

    highschool_id = getattr(student, 'highschool_id', None)
    return highschool_id in allowed


def _model(dotted):
    """Import a note model lazily so this module stays import-safe."""
    from importlib import import_module

    module_path, name = dotted.rsplit('.', 1)
    return getattr(import_module(module_path), name)


def _register_note_type(slug, model, owner_field, owner_model,
                        permission, scope=None, add_to=None, label=None):
    """Declare a note kind and wire its add_new action."""
    note_type = note_types.register(NoteType(
        slug=slug,
        model=model,
        owner_field=owner_field,
        owner_model=owner_model,
        permission=permission,
        scope=scope,
    ))

    def handler(request, _slug=slug, _add_to=add_to or owner_field):
        from cis.views.note import add_new_note

        registered = note_types.get(_slug)
        if not registered.may(request):
            return JsonResponse({
                'status': 'error',
                'message': 'You are not authorized to perform this action.',
            }, status=403)
        return add_new_note(request, _add_to)

    handler.__name__ = slug
    add_new_actions.action(
        GROUP, label=label or slug, scope=['detail'], slug=slug,
        permission=permission,
    )(handler)
    return note_type


def register_all():
    """Called at import; kept as a function so tests can reason about it."""
    from cis.models.course import Course
    from cis.models.customuser import CustomUser
    from cis.models.event import Event
    from cis.models.highschool import HighSchool
    from cis.models.highschool_administrator import HSAdministrator
    from cis.models.note import (
        ClassSectionNote, CourseNote, EventNote, HighSchoolNote,
        HSAdministratorNote, StudentNote, TeacherApplicationNote, TeacherNote,
    )
    from cis.models.section import ClassSection
    from cis.models.student import Student
    from cis.models.teacher import Teacher

    # --- CE-only: no non-cis template posts these ------------------------
    _register_note_type(
        'coursenote', CourseNote, 'course', Course,
        permission=_cis, add_to='course', label='Add Course Note')

    _register_note_type(
        'highschoolnote', HighSchoolNote, 'highschool', HighSchool,
        permission=_cis, add_to='highschool', label='Add High School Note')

    # pd_event exposes the event detail page (which posts this) from both its
    # ce and faculty URL modules, so CE-only would break the faculty portal.
    _register_note_type(
        'eventnote', EventNote, 'event', Event,
        permission=user_has_cis_or_faculty_role, add_to='event',
        label='Add Event Note')

    _register_note_type(
        'studentnote', StudentNote, 'student', Student,
        permission=_cis, add_to='student', label='Add Student Note')

    # degree_pathway posts this from degree_plan/hs_admin/detail.html as well
    # as its ce page, so HS admins need it — scoped to their own students.
    _register_note_type(
        'studentplannote', StudentNote, 'student', Student,
        permission=_cis_or_hs_admin, scope=_student_in_hs_admin_scope,
        add_to='studentplan', label='Add Student Plan Note')

    # PT-9: hsadminnote is CE-only; add_new_note enforces this twice
    # internally as well. Kept here so the gate is visible at the entry point.
    _register_note_type(
        'hsadminnote', HSAdministratorNote, 'hsadmin', HSAdministrator,
        permission=_cis, add_to='hsadmin', label='Add HS Admin Note')

    # PT-23: teacher notes are CE-only. The guard moves off the if-chain.
    _register_note_type(
        'teachernote', TeacherNote, 'teacher', Teacher,
        permission=_cis, add_to='teacher', label='Add Instructor Note')

    # --- Shared with other portals ---------------------------------------
    # Posted from the instructor portal as well as cis.
    _register_note_type(
        'classsectionnote', ClassSectionNote, 'class_section', ClassSection,
        permission=_cis_or_instructor, add_to='classsection',
        label='Add Class Section Note')

    # Posted from the HS admin portal ("Reply to Note"). Scoped to the
    # schools that admin manages — this path had no check at all before.
    _register_note_type(
        'student_replynote', StudentNote, 'student', Student,
        permission=_cis_or_hs_admin, scope=_student_in_hs_admin_scope,
        add_to='student_reply', label='Reply to Student Note')

    # support_ticket posts this from its student, instructor and
    # highschool_admin views, so it cannot be CE-only.
    _register_note_type(
        'ticketnote', _model('support_ticket.models.ticket.TicketNote'),
        'ticket', _model('support_ticket.models.ticket.Ticket'),
        permission=_ticket_participant, add_to='ticket',
        label='Add Ticket Note')

    # --- Behaviour preserved pending evidence ----------------------------
    # No portal template was found posting these beyond the CE detail pages,
    # but an applicant- or faculty-facing caller cannot be ruled out, and
    # tightening on a guess would break a feature silently. Left as today
    # (any authenticated user) and flagged for a follow-up.
    _register_note_type(
        'teacherapplicationnote', TeacherApplicationNote,
        'teacher_application', _model('cis.models.customuser.CustomUser'),
        permission=_authenticated, add_to='teacherapplication',
        label='Add Application Note')

    _register_note_type(
        'visitreportnote', _model('cis.models.note.ClassVisitReportNote'),
        'visit_report', CustomUser,
        permission=_authenticated, add_to='visitreport',
        label='Add Visit Report Note')


register_all()
