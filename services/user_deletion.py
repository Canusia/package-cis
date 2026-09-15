"""Hard-delete a CE staff account without tripping PROTECT or losing authorship.

About 100 reverse relations point at CustomUser, and roughly 65 of them are
PROTECT, so a bare `user.delete()` raises ProtectedError for nearly every staff
account that has ever written a note. Each relation that matters is classified
here into one strategy:

    REASSIGN  point the row at the superuser performing the delete
    NULLIFY   clear a nullable "assigned to" style reference
    DELETE    remove a row that only means something for this user
    BLOCK     the user holds a role/identity record -- refuse the delete

The registry is keyed by (model label, field name). Any PROTECT or RESTRICT
relation that is NOT in the registry blocks the delete ("fail closed"), so a
package that adds a new user FK stops deletes rather than breaking them;
cis.tests.test_user_deletion pins that every installed relation is classified.

Audit logs (impersonate.ImpersonationLog, admin.LogEntry) are deliberately not
reassigned -- crediting the acting admin with impersonations or admin changes
they never made would falsify the trail. They keep their CASCADE, and a
snapshot of them goes into the deletion LogEntry that delete_user() writes.
"""
import json
from dataclasses import dataclass, field

from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction

from cis.models.customuser import CustomUser

REASSIGN = 'reassign'
NULLIFY = 'nullify'
DELETE = 'delete'
BLOCK = 'block'

REGISTRY = {
    # -- authorship: reassigned to the acting superuser ---------------------
    ('announcement.BulkMessage', 'createdby'): REASSIGN,
    ('cis.ApplicantCourseReviewer', 'reviewer'): REASSIGN,
    ('cis.ClassSectionNote', 'createdby'): REASSIGN,
    ('cis.ClassVisitReportNote', 'createdby'): REASSIGN,
    ('cis.CourseNote', 'createdby'): REASSIGN,
    ('cis.Event', 'created_by_tbd'): REASSIGN,
    ('cis.EventCohort', 'created_by'): REASSIGN,
    ('cis.EventNote', 'createdby'): REASSIGN,
    ('cis.EventSpeaker', 'created_by'): REASSIGN,
    ('cis.FacultyCoordinatorNote', 'createdby'): REASSIGN,
    ('cis.HSAdministratorNote', 'createdby'): REASSIGN,
    ('cis.HighSchoolNote', 'createdby'): REASSIGN,
    ('cis.HighSchoolTranscript', 'uploaded_by'): REASSIGN,
    ('cis.StudentNote', 'createdby'): REASSIGN,
    ('cis.TeacherApplicationNote', 'createdby'): REASSIGN,
    ('cis.TeacherNote', 'createdby'): REASSIGN,
    ('degree_pathway.StudentPlanNote', 'createdby'): REASSIGN,
    ('docrepo.DocRepo', 'uploaded_by'): REASSIGN,
    ('drop_wd.DropWDRequest', 'created_by'): REASSIGN,
    ('drop_wd.DropWDRequest', 'processed_by'): REASSIGN,
    ('future_sections.SectionRequestReview', 'reviewer'): REASSIGN,
    ('instructor_app.ApplicantCourseReviewer', 'reviewer'): REASSIGN,
    ('instructor_app.TeacherApplicationNote', 'createdby'): REASSIGN,
    ('invoice.Invoice', 'created_by'): REASSIGN,
    ('invoice.InvoiceItem', 'created_by'): REASSIGN,
    ('invoice.InvoiceNote', 'createdby'): REASSIGN,
    ('mou.MOU', 'created_by'): REASSIGN,
    ('mou.MOUNote', 'createdby'): REASSIGN,
    ('mou.MOUSignator', 'created_by'): REASSIGN,
    ('new_school_application.HighSchoolApplicationCourseReview', 'reviewer'): REASSIGN,
    ('pd_event.Event', 'created_by'): REASSIGN,
    ('support_ticket.Ticket', 'submitted_by'): REASSIGN,
    ('support_ticket.TicketNote', 'createdby'): REASSIGN,

    # -- live assignments: cleared -----------------------------------------
    ('cis.FutureProjection', 'created_by'): NULLIFY,
    ('cis.StudentRecommendation', 'submitted_by'): NULLIFY,
    ('cis.TeacherApplication', 'assigned_to'): NULLIFY,
    ('degree_pathway.StudentPlan', 'advisor'): NULLIFY,
    ('future_sections.FutureProjection', 'created_by'): NULLIFY,
    ('instructor_app.TeacherApplication', 'assigned_to'): NULLIFY,
    ('mou.MOU', 'manager'): NULLIFY,
    ('mou.MOUSignator', 'college_user'): NULLIFY,
    ('student_transactions.StudentTransaction', 'created_by'): NULLIFY,
    ('support_ticket.Ticket', 'assigned_to'): NULLIFY,
    ('support_ticket.TicketType', 'assigned_to'): NULLIFY,

    # -- rows that only mean something for this user: removed --------------
    ('alerts.Alert', 'recipient'): DELETE,
    ('cis.HighSchoolCollegeAdvisor', 'advisor'): DELETE,
    ('report.ReportScheduler', 'created_by'): DELETE,

    # -- role / identity records: refuse -----------------------------------
    ('cis.CohortParticipant', 'user'): BLOCK,
    ('cis.CourseAdministrator', 'user'): BLOCK,
    ('cis.DistrictAdministrator', 'user'): BLOCK,
    ('cis.EventAttendee', 'user'): BLOCK,
    ('cis.FacultyCoordinator', 'user'): BLOCK,
    # CASCADE, but it is a faculty role assignment -- deleting it silently
    # would be exactly the role-stripping the delete is meant to refuse.
    ('cis.FacultyTeacherAssignment', 'user'): BLOCK,
    ('cis.HSAdministrator', 'user'): BLOCK,
    ('cis.Speaker', 'user'): BLOCK,
    ('cis.Student', 'user'): BLOCK,
    ('cis.Teacher', 'user'): BLOCK,
    ('cis.TeacherApplicant', 'user'): BLOCK,
    ('cis.TeacherApplication', 'user'): BLOCK,
    ('cis.TechCenterStaff', 'user'): BLOCK,
    ('instructor_app.TeacherApplicant', 'user'): BLOCK,
    ('instructor_app.TeacherApplication', 'user'): BLOCK,
    # A signature is a legal record; crediting it to another person is not
    # an authorship fix, it is forgery.
    ('mou.MOUSignature', 'signator'): BLOCK,
}

# CASCADE relations whose rows are an audit trail. Not reassigned (see module
# docstring); counted and snapshotted into the deletion LogEntry instead.
AUDIT_CASCADES = {
    ('impersonate.ImpersonationLog', 'impersonator'),
    ('impersonate.ImpersonationLog', 'impersonating'),
    ('admin.LogEntry', 'user'),
}

_FAIL_CLOSED = (models.PROTECT, models.RESTRICT)


@dataclass
class Effect:
    label: str        # 'cis.StudentNote.createdby'
    verbose: str      # 'student notes'
    strategy: str
    count: int


@dataclass
class DeletionPlan:
    user: CustomUser
    blockers: list = field(default_factory=list)   # human-readable reasons
    effects: list = field(default_factory=list)    # Effect, count > 0 only

    @property
    def deletable(self):
        return not self.blockers


class UserDeletionBlocked(Exception):
    def __init__(self, plan):
        self.plan = plan
        super().__init__('; '.join(plan.blockers))


def user_relations():
    """Yield (key, relation, strategy) for every non-M2M reverse relation.

    strategy is None for relations the registry does not name and that do not
    need it (SET_NULL, DO_NOTHING, plain CASCADE); unclassified PROTECT/RESTRICT
    relations come back as BLOCK.
    """
    for rel in CustomUser._meta.related_objects:
        if rel.many_to_many:
            continue
        key = (rel.related_model._meta.label, rel.field.name)
        strategy = REGISTRY.get(key)
        if strategy is None and key in AUDIT_CASCADES:
            strategy = 'audit'
        if strategy is None and rel.on_delete in _FAIL_CLOSED:
            strategy = 'unclassified'
        yield key, rel, strategy


def _rows(rel, user):
    return rel.related_model._base_manager.filter(**{rel.field.name: user})


def preflight(user):
    """Read-only: what delete_user() would do to `user`, and what blocks it."""
    plan = DeletionPlan(user=user)
    for key, rel, strategy in user_relations():
        if strategy is None:
            continue
        count = _rows(rel, user).count()
        if not count:
            continue
        label = '.'.join(key)
        verbose = str(rel.related_model._meta.verbose_name_plural)
        if strategy == BLOCK:
            plan.blockers.append(f'has {count} {verbose} record(s) ({label})')
        elif strategy == 'unclassified':
            plan.blockers.append(
                f'has {count} row(s) in an unclassified reference ({label})')
        else:
            plan.effects.append(Effect(label, verbose, strategy, count))
    return plan


def _impersonation_snapshot(user):
    try:
        from impersonate.models import ImpersonationLog
    except ImportError:  # pragma: no cover - app not installed on this tenant
        return []
    logs = ImpersonationLog.objects.filter(
        models.Q(impersonator=user) | models.Q(impersonating=user)
    ).select_related('impersonator', 'impersonating').order_by('session_started_at')
    return [
        {
            'impersonator': log.impersonator.email,
            'impersonating': log.impersonating.email,
            'started': log.session_started_at.isoformat() if log.session_started_at else None,
            'ended': log.session_ended_at.isoformat() if log.session_ended_at else None,
        }
        for log in logs
    ]


def delete_user(user, *, acting_user):
    """Apply the plan and delete `user`, atomically.

    Raises UserDeletionBlocked (and changes nothing) if preflight finds a
    blocker. Returns the DeletionPlan that was applied.
    """
    with transaction.atomic():
        user = CustomUser.objects.select_for_update().get(pk=user.pk)
        plan = preflight(user)
        if not plan.deletable:
            raise UserDeletionBlocked(plan)

        snapshot = {
            'deleted_user': {
                'id': user.pk, 'email': user.email, 'username': user.username,
                'name': f'{user.first_name} {user.last_name}'.strip(),
            },
            'effects': [
                {'relation': e.label, 'strategy': e.strategy, 'count': e.count}
                for e in plan.effects
            ],
            'impersonation_log': _impersonation_snapshot(user),
        }

        for key, rel, strategy in user_relations():
            rows = _rows(rel, user)
            if strategy == REASSIGN:
                rows.update(**{rel.field.name: acting_user})
            elif strategy == NULLIFY:
                rows.update(**{rel.field.name: None})
            elif strategy == DELETE:
                rows.delete()

        # Written before user.delete() and attributed to the actor, so the
        # admin.LogEntry cascade on the deleted user cannot take it with it.
        LogEntry.objects.create(
            user=acting_user,
            content_type=ContentType.objects.get_for_model(CustomUser),
            object_id=str(user.pk),
            object_repr=f'{snapshot["deleted_user"]["name"]} <{user.email}>'[:200],
            action_flag=DELETION,
            change_message=json.dumps(snapshot),
        )

        user.delete()
    return plan
