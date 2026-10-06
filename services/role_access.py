"""Shared role-access lifecycle for CE-managed roles.

Generalises cis/services/hs_admin_role.py, which was written first for high
school administrators. The contract is identical for every role:

  * deleting a role record NEVER deletes the CustomUser. CustomUser is the
    target of ~20 PROTECT foreign keys, so user.delete() raises ProtectedError
    for most real accounts. Swallowing that (the historical bug) left accounts
    carrying a role group with no record behind them.
  * the group is revoked as a separate, explicit step, refused while any record
    remains, so a stale browser tab or forged request cannot strip access from
    someone still holding the role.

A policy is data, not behaviour: adding a role means adding a policy, not a
new service module with its own copy of these rules.
"""
import logging
from dataclasses import dataclass, field

from django.apps import apps
from django.contrib.auth.models import Group
from django.db import transaction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoleAccessPolicy:
    """Describes one CE-managed role.

    group_name:        the auth Group that grants portal access.
    record_model_path: 'app_label.ModelName' of the role record.
    user_field:        the field on that model pointing at CustomUser.
    extra_blockers:    reserved for future roles that need to guard on more
                        than one model; not used by any policy yet.
    """
    group_name: str
    record_model_path: str
    user_field: str = 'user'
    extra_blockers: tuple = field(default_factory=tuple)

    @property
    def model(self):
        return apps.get_model(self.record_model_path)


def has_remaining_records(policy, user):
    """True while the user still has at least one role record."""
    return policy.model.objects.filter(**{policy.user_field: user}).exists()


def dangling_users(policy):
    """Users holding the role's group with no role record behind it.

    The role models link to CustomUser with OneToOneField, so the reverse
    accessor is the lowercased model name and `<accessor>__isnull=True` is the
    'has no record' filter.
    """
    from cis.models.customuser import CustomUser

    accessor = policy.model.__name__.lower()

    # Downstream consumers (dangling-account list/serializer views) render
    # user.get_roles(), which reads self.groups.all() per row. Without this
    # prefetch that is an extra query per row on every page of a server-side
    # DataTable — an N+1 that's invisible in a unit test.
    return CustomUser.objects.filter(
        groups__name=policy.group_name,
        **{f'{accessor}__isnull': True},
    ).prefetch_related('groups').distinct()


def revoke_access(policy, user):
    """Drop the role's group once the user holds no role record.

    No-op while any record remains — that guard is the control that stops a
    stale tab or a forged request from stripping access from an active user,
    so callers must not skip it.

    Never deletes the account. Never touches any other role.

    Returns True if the group was revoked.
    """
    if has_remaining_records(policy, user):
        return False

    with transaction.atomic():
        try:
            user.groups.remove(Group.objects.get(name=policy.group_name))
        except Group.DoesNotExist:
            logger.warning(
                '%s group missing; run init_groups', policy.group_name)

        logger.info('Revoked %s role for user %s', policy.group_name, user.pk)

    return True


# Reverse one-to-ones on CustomUser that grant no role. Anything NOT listed
# here counts as a role record, so a package that adds a new one-to-one hides
# its users from roleless_users() rather than exposing them to a delete.
NON_ROLE_ONE_TO_ONES = frozenset({'authtoken.Token'})


def role_record_relations():
    """Reverse one-to-one relations from CustomUser to a role record
    (Student, Teacher, HSAdministrator, TeacherApplicant, ...)."""
    from cis.models.customuser import CustomUser

    return [
        rel for rel in CustomUser._meta.related_objects
        if rel.one_to_one
        and rel.related_model._meta.label not in NON_ROLE_ONE_TO_ONES
    ]


def roleless_users():
    """Accounts with no role at all: no auth group AND no role record.

    Both conditions are required. A role record without its group is a
    dangling account (see dangling_users) and still belongs to someone; a
    group without a record is the other dangling shape. Superusers are left
    out -- they need no group to have access.

    Usually these are logins left behind by revoke_access() on the Dangling
    Accounts tabs, which drops the group and deliberately keeps the account.
    Listed on the No Role tab of /ce/users/.
    """
    from cis.models.customuser import CustomUser

    no_record = {
        f'{rel.get_accessor_name()}__isnull': True
        for rel in role_record_relations()
    }
    # groups__isnull=True only matches users with no group row at all, so the
    # m2m join cannot duplicate rows and no distinct() is needed.
    return CustomUser.objects.filter(
        groups__isnull=True,
        is_superuser=False,
        **no_record,
    )


def is_roleless(user):
    """Re-check one account right before acting on it."""
    return roleless_users().filter(pk=user.pk).exists()
