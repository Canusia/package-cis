"""Re-point a role record at a different, existing CustomUser.

Used when the same person ended up with two accounts — e.g. an instructor
whose email already belongs to the account they use as a high school
administrator. Editing the email on the record's own account fails on the
unique email/username, so CE links the role record to the existing account
instead.

Only the role record moves (with everything hanging off it: school links,
certificates, positions, notes about the person). Anything keyed on the old
CustomUser itself — applications, event attendance, login history, notes the
old account wrote — stays where it is. The old account loses the role's group
and, if that leaves it with no role at all, is deactivated so nobody can log
in to an empty account. It is never deleted.
"""
import json
from dataclasses import dataclass
from typing import Callable

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db import transaction


class RelinkError(Exception):
    """The relink was refused; the message is safe to show CE staff."""


def _grant_instructor(record, user):
    group, _ = Group.objects.get_or_create(name='instructor')
    user.groups.add(group)


def _revoke_instructor(user):
    from cis.services.instructor_role import INSTRUCTOR
    from cis.services.role_access import revoke_access
    revoke_access(INSTRUCTOR, user)


def _grant_hs_admin(record, user):
    # Mirrors cis.signals.highschool_admin.hs_position_updated: the group
    # tracks active positions, which move with the record.
    if record.get_highschools():
        group, _ = Group.objects.get_or_create(name='highschool_admin')
        user.groups.add(group)


def _revoke_hs_admin(user):
    from cis.services.hs_admin_role import revoke_hs_admin_access
    revoke_hs_admin_access(user)


@dataclass(frozen=True)
class RelinkPolicy:
    label: str                      # shown to CE staff, e.g. 'instructor'
    record_model_path: str
    grant: Callable                 # (record, new_user) -> None
    revoke: Callable                # (old_user) -> None

    @property
    def model(self):
        from django.apps import apps
        return apps.get_model(self.record_model_path)


INSTRUCTOR_RELINK = RelinkPolicy(
    label='instructor',
    record_model_path='cis.Teacher',
    grant=_grant_instructor,
    revoke=_revoke_instructor,
)

HS_ADMIN_RELINK = RelinkPolicy(
    label='high school administrator',
    record_model_path='cis.HSAdministrator',
    grant=_grant_hs_admin,
    revoke=_revoke_hs_admin,
)


def find_target(email):
    """The existing account for `email`, or None."""
    from cis.models.customuser import CustomUser

    email = (email or '').strip()
    if not email:
        return None
    return CustomUser.objects.filter(email__iexact=email).first()


def check_relink(policy, record, target):
    """Raise RelinkError if `record` cannot be moved to `target`."""
    if target is None:
        raise RelinkError('No account exists with that email address.')
    if target.pk == record.user_id:
        raise RelinkError(
            f'This {policy.label} is already linked to that account.')
    if policy.model.objects.filter(user=target).exists():
        raise RelinkError(
            f'That account already has its own {policy.label} record. '
            'Only one is allowed per account.')


def _is_roleless(user):
    from cis.services.role_access import roleless_users
    return roleless_users().filter(pk=user.pk).exists()


def relink(policy, record, target, acting_user):
    """Move `record` to `target`. Returns the old CustomUser.

    All or nothing: a failure at any step leaves the record, both accounts'
    groups and their active flags as they were.
    """
    check_relink(policy, record, target)

    with transaction.atomic():
        record = policy.model.objects.select_for_update().get(pk=record.pk)
        old_user = record.user

        record.user = target
        record.save(update_fields=['user'])

        if not target.is_active:
            target.is_active = True
            target.save(update_fields=['is_active'])

        policy.grant(record, target)
        policy.revoke(old_user)

        old_deactivated = False
        if not old_user.is_staff and _is_roleless(old_user):
            old_user.is_active = False
            old_user.save(update_fields=['is_active'])
            old_deactivated = True

        LogEntry.objects.create(
            user=acting_user,
            content_type=ContentType.objects.get_for_model(record),
            object_id=str(record.pk),
            object_repr=str(record)[:200],
            action_flag=CHANGE,
            change_message=json.dumps({
                'relinked_user': {
                    'from': {'id': old_user.pk, 'email': old_user.email},
                    'to': {'id': target.pk, 'email': target.email},
                    'old_user_deactivated': old_deactivated,
                },
            }),
        )

    return old_user
