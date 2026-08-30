"""High school administrator role lifecycle.

Modelled on instructor_app/services/applicant_role.py: deleting an
administrator removes the HSAdministrator record, never the CustomUser.
CustomUser is the target of ~20 PROTECT foreign keys (Note.createdby among
them), so user.delete() raises ProtectedError for anyone who has ever created a
record. The previous implementation swallowed that in a bare except, which left
accounts in the highschool_admin group with no HSAdministrator record — the
"dangling accounts" the CE list page now surfaces.
"""
import logging

from django.contrib.auth.models import Group

logger = logging.getLogger(__name__)

HS_ADMIN_GROUP = 'highschool_admin'


def has_remaining_hs_admin_records(user):
    """True while the user still has at least one HSAdministrator record."""
    from cis.models.highschool_administrator import HSAdministrator

    return HSAdministrator.objects.filter(user=user).exists()


def has_remaining_hs_admin_roles(user):
    """True while the user still holds at least one role at a high school."""
    from cis.models.highschool_administrator import HSAdministratorPosition

    return HSAdministratorPosition.objects.filter(hsadmin__user=user).exists()


def revoke_hs_admin_access(user):
    """Drop the highschool_admin role once the user holds no roles at schools.

    No-op while any HSAdministratorPosition remains — that check is the guard
    against a stale browser tab or a hand-crafted request stripping access from
    a working administrator, so callers must not skip it.

    Any leftover HSAdministrator shell (a record with no positions) is removed
    too, so the user cannot reappear as a dangling account.

    Never touches any other role, and never deletes the user account.

    Returns True if the role was revoked.
    """
    from cis.models.highschool_administrator import HSAdministrator
    from cis.models.note import HSAdministratorNote

    if has_remaining_hs_admin_roles(user):
        return False

    try:
        user.groups.remove(Group.objects.get(name=HS_ADMIN_GROUP))
    except Group.DoesNotExist:
        logger.warning('%s group missing; run init_groups', HS_ADMIN_GROUP)

    records = HSAdministrator.objects.filter(user=user)
    HSAdministratorNote.objects.filter(hsadmin__in=records).delete()
    records.delete()

    logger.info('Revoked %s role for user %s', HS_ADMIN_GROUP, user.pk)
    return True
