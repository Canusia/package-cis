"""Staff-account bulk actions for /ce/users/ — enable, disable, delete.

Registered on a cis-owned ActionRegistry, so the buttons a user sees are
derived from the registry (`for_scope('bulk', user)`) rather than hand-built
per view, and another package can add an action here without touching the
page or the tenant table config.

The registry instance is deliberately created here rather than in a host
`myce/component_registry/user.py`: no tenant ships one, and cis/urls.py imports
cis/views/users.py on every deployment, so depending on a host module would
hard-crash tenants that lack it. `ActionRegistry` itself is present in every
tenant's myce/component_registry, so importing the class is safe — the same
reasoning as cis/actions/registry.py.

Responses use the ActionRegistry envelope that action_registry.js understands:
`call`/`onBulkActionComplete` for "reload the table and say what happened", and
`modal` for the delete confirmation. Permissions are declared per action and
enforced twice by the registry: `for_scope` hides the button, `dispatch`
refuses the request.
"""
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse

from myce.component_registry import ActionRegistry

from cis.models.customuser import CustomUser
from cis.services import user_deletion

user_actions = ActionRegistry()

#: Rendered as buttons on the /ce/users/ table.
BULK = 'bulk'
#: Dispatchable but never rendered: reached from the delete confirmation form.
DISPATCH_ONLY = 'dispatch'

GROUP = 'accounts'


def can_edit_users(user):
    return bool(getattr(user, 'can_edit_users', False))


def is_superuser(user):
    return bool(getattr(user, 'is_superuser', False))


def registered_slugs():
    """Every slug this registry can dispatch, buttons and form targets alike."""
    slugs = set()
    for scope in (BULK, DISPATCH_ONLY):
        for group in user_actions.for_scope(scope).values():
            slugs.update(group['actions'])
    return slugs


def selected_staff(request):
    """Resolve ids[] to CE accounts the requester may act on.

    Returns (users, skipped). IDs are CustomUser AutoField ints; anything
    unparseable, outside the `ce` group (the table's scope), the requester's
    own account, or -- for non-superusers -- a superuser, is counted as
    skipped. The action handlers never see a row they may not touch.
    """
    ids = request.POST.getlist('ids[]') or request.GET.getlist('ids[]')

    valid_ids = set()
    for record_id in ids:
        try:
            valid_ids.add(int(record_id))
        except (ValueError, TypeError):
            continue

    users = CustomUser.objects.filter(
        id__in=valid_ids, groups__name='ce'
    ).exclude(pk=request.user.pk).distinct()
    if not request.user.is_superuser:
        users = users.exclude(is_superuser=True)

    users = list(users.order_by('last_name', 'first_name'))
    return users, len(ids) - len(users)


def _complete(message, status='success', title='Done'):
    return JsonResponse({
        'outcome': 'call',
        'fn': 'onBulkActionComplete',
        'args': {'title': title, 'message': message, 'status': status},
    })


def _set_active(request, target):
    users, skipped = selected_staff(request)

    updated = 0
    for user in users:
        if user.is_active == target:
            skipped += 1
            continue
        user.is_active = target
        # save(), not queryset.update(): CustomUser has HistoricalRecords.
        user.save(update_fields=['is_active'])
        updated += 1

    verb = 'enabled' if target else 'disabled'
    return _complete(
        f'{updated} account(s) {verb}, {skipped} skipped '
        f'(already {verb}, not permitted, or not found).')


@user_actions.action(
    GROUP, slug='enable', label='Enable Selected', scope=[BULK],
    icon='fas fa-user-check', btn_class='btn-primary',
    confirm='Enable the selected account(s)? They will be able to sign in.',
    permission=can_edit_users)
def enable_accounts(request):
    return _set_active(request, True)


@user_actions.action(
    GROUP, slug='disable', label='Disable Selected', scope=[BULK],
    icon='fas fa-user-slash', btn_class='btn-warning',
    confirm='Disable the selected account(s)? They will be signed out and '
            'unable to sign in until re-enabled.',
    permission=can_edit_users)
def disable_accounts(request):
    return _set_active(request, False)


@user_actions.action(
    GROUP, slug='delete_preflight', label='Delete Selected', scope=[BULK],
    icon='fas fa-trash', btn_class='btn-danger',
    permission=is_superuser)
def delete_preflight(request):
    """Read-only: what deleting each selected account would do, or why not.

    Returns the confirmation modal. Its form posts the `delete` slug back to
    the same endpoint with only the deletable ids.
    """
    users, skipped = selected_staff(request)
    plans = [user_deletion.preflight(user) for user in users]

    return JsonResponse({
        'outcome': 'modal',
        'html': render_to_string('cis/users/delete_preflight.html', {
            'plans': plans,
            'skipped': skipped,
            'deletable_ids': [p.user.pk for p in plans if p.deletable],
            'bulk_actions_url': reverse('cis:users_bulk_action'),
            'strategy_verbs': {
                user_deletion.REASSIGN: 'reassigned to you',
                user_deletion.NULLIFY: 'cleared',
                user_deletion.DELETE: 'removed',
                'audit': 'removed (kept in the deletion log)',
            },
        }, request=request),
    })


@user_actions.action(
    GROUP, slug='delete', label='Delete Accounts', scope=[DISPATCH_ONLY],
    permission=is_superuser)
def delete_accounts(request):
    """Execute the delete. Each account gets its own transaction, so one
    blocked account does not roll back the others."""
    users, skipped = selected_staff(request)

    deleted = blocked = 0
    for user in users:
        try:
            user_deletion.delete_user(user, acting_user=request.user)
            deleted += 1
        except user_deletion.UserDeletionBlocked:
            blocked += 1

    return _complete(
        f'{deleted} account(s) deleted, {blocked} blocked, '
        f'{skipped} skipped (not permitted or not found).')
