"""
Staff User Views
"""
import inspect
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse

from django_login_history.models import Login

from rest_framework import viewsets

from cis.actions.user import registered_slugs, user_actions
from cis.menu import draw_menu, cis_menu
from cis.models.customuser import CustomUser
from cis.serializers.user import (
    StaffUserSerializer, LockedUserSerializer, RolelessUserSerializer,
)
from cis.services import user_deletion
from cis.services.role_access import is_roleless, roleless_users
from cis.services.table_configs import get_table_config
from cis.utils import CIS_user_only

from cis.forms.user import UserForm

build_users_table_config = get_table_config('users_table').build_config
build_locked_users_table_config = get_table_config('locked_users_table').build_config

logger = logging.getLogger(__name__)


def _supported_kwargs(build_config, kwargs):
    """Drop kwargs a tenant's build_config does not accept.

    The users table config lives in each tenant's TABLE_CONFIGS_APP, so a
    tenant can bump cis without porting its copy. Passing bulk_actions to a
    build_config that predates them raised TypeError -- a 500 on /ce/users for
    a tenant that had not adopted the feature. Gate on the signature instead:
    an un-ported tenant renders the table as before, and adopts the bulk
    actions by accepting the two kwargs (cis#18).
    """
    params = inspect.signature(build_config).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    return {name: value for name, value in kwargs.items() if name in params}

# The one bulk action on /ce/users/locked/. Kept at module level because both
# the page view (which renders the buttons) and do_locked_bulk_action (which
# validates the slug) have to agree on it.
LOCKED_BULK_ACTIONS = {
    'unlock': {
        'label': 'Unlock Selected Accounts',
        'icon': 'fas fa-unlock',
        'btn_class': 'btn-primary',
        'confirm': 'Unlock the selected account(s)? They will be able to sign in '
                   'again and their failed-attempt counter is reset to zero.',
        'method': 'POST',
    },
}

# The No Role tab of /ce/users/. The button only previews: `preview_delete`
# answers with the per-account preflight in a modal, whose confirm form posts
# `delete_account` back to do_roleless_bulk_action. Deliberately not named
# `delete_preflight`/`delete` -- those are the superuser-only staff-account
# slugs on cis.actions.user, and this tab renders for every can_edit_users
# user.
ROLELESS_BULK_ACTIONS = {
    'preview_delete': {
        'label': 'Delete Selected Accounts',
        'icon': 'fas fa-trash-alt',
        'btn_class': 'btn-danger',
        'method': 'POST',
    },
}
ROLELESS_ACTIONS = ('preview_delete', 'delete_account')
ROLELESS_API_URL = '/ce/api/user-roleless?format=datatables'


class StaffUserViewSet(viewsets.ReadOnlyModelViewSet):
    """CE staff accounts behind the /ce/users/ DataTable.

    Gated the same way the page is: a CIS role plus `can_edit_users`. The
    permission class can only express the first half, so the second is
    enforced on the queryset -- an authenticated CE user without
    `manage_staff_accounts` gets an empty table rather than the roster.
    """
    serializer_class = StaffUserSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        if not self.request.user.can_edit_users:
            return CustomUser.objects.none()

        records = CustomUser.objects.filter(groups__name='ce')

        # Matches the Account Enabled select in the page filter form.
        is_active = self.request.query_params.get('is_active', '')
        if is_active in ('true', 'false'):
            records = records.filter(is_active=(is_active == 'true'))

        return records.order_by('-created_at')


class LockedUserViewSet(viewsets.ReadOnlyModelViewSet):
    """Accounts locked out by failed sign-in attempts, behind /ce/users/locked/.

    Deliberately NOT restricted to the `ce` group: lockout is a property of the
    account, not of a role, so a locked student, instructor or HS admin belongs
    on this page exactly as much as a locked staffer. `roles` is the column
    that tells them apart.

    Gated like StaffUserViewSet -- CIS role via the permission class, plus
    `can_edit_users` on the queryset, which the permission class cannot
    express. Unlocking is a privileged action, so the page gate alone is not
    enough: see do_locked_bulk_action, which repeats the check.
    """
    serializer_class = LockedUserSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        if not self.request.user.can_edit_users:
            return CustomUser.objects.none()

        # active_lock_q drops locks that have timed out but not yet been
        # cleared (that happens lazily, on the account's next sign-in).
        return CustomUser.objects.filter(
            CustomUser.active_lock_q()
        ).prefetch_related('groups').order_by('last_name', 'first_name')


class RolelessUserViewSet(viewsets.ReadOnlyModelViewSet):
    """Accounts with no group and no role record, behind the No Role tab of
    /ce/users/ (cis.services.role_access.roleless_users).

    Gated like LockedUserViewSet: CIS role via the permission class, plus
    `can_edit_users` on the queryset. do_roleless_bulk_action repeats the
    check, since the feed being empty does not stop a forged POST.
    """
    serializer_class = RolelessUserSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        if not self.request.user.can_edit_users:
            return CustomUser.objects.none()
        return roleless_users().order_by('last_name', 'first_name')


def _roleless_users_table_config():
    """The tenant's No Role table config, or None if it doesn't ship one yet.

    Resolved per request, not at import time: get_table_config() is a bare
    import, and a module-level call would turn a tenant that has not added
    roleless_users_table.py into an ImportError for the whole cis URLconf.
    Without it the tab is simply not rendered (system check cis.W005); the
    feed and the bulk endpoint do not depend on it.

    Only the module being absent means "not adopted". An ImportError raised
    from inside a tenant module that does exist is a real breakage and
    propagates, as in cis.services.tenant_services.get_tenant_override.
    """
    try:
        module = get_table_config('roleless_users_table')
    except ModuleNotFoundError as exc:
        if exc.name == f'{settings.TABLE_CONFIGS_APP}.services.roleless_users_table':
            return None
        raise
    return module.build_config(
        variant='roleless_users_index',
        api_url=ROLELESS_API_URL,
        bulk_actions=ROLELESS_BULK_ACTIONS,
        bulk_actions_url=reverse('cis:roleless_users_bulk_action'),
    )


def locked_index(request):
    '''
    Locked accounts index page
    '''
    menu = draw_menu(cis_menu, 'users', 'locked_users')

    if not request.user.can_edit_users:
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger')
        return redirect('cis:dashboard')

    template = 'cis/users/locked_index.html'

    return render(
        request,
        template,
        {
            'page_title': 'Locked Accounts',
            'menu': menu,
            'max_failed_logins': CustomUser.MAX_FAILED_LOGINS,
            'lockout_minutes': CustomUser.lockout_minutes(),
            'locked_users_table': build_locked_users_table_config(
                variant='locked_users_index',
                api_url='/ce/api/locked-user?format=datatables',
                bulk_actions=LOCKED_BULK_ACTIONS,
                bulk_actions_url=reverse('cis:locked_users_bulk_action'),
            ),
        })


def do_locked_bulk_action(request):
    """Bulk actions for the Locked Accounts page.

    `ids[]` are CustomUser ids -- an integer AutoField -- so the id guard below
    validates with int(), not uuid.UUID(). The unknown-action check runs before
    the POST-only check, so an unknown action arriving over GET cannot reach a
    mutation, matching cis.views.faculty.do_dangling_bulk_action.

    The `can_edit_users` gate is repeated here rather than left to the page:
    unlocking restores sign-in to an account that the brute-force guard shut
    off, so the endpoint has to stand on its own.

    Only rows that are actually locked are touched. Ids that name an unlocked
    account -- or no account at all -- are counted as skipped rather than
    silently dropped, so a stale table selection reports honestly instead of
    claiming more unlocks than it performed.
    """
    action = request.POST.get('action') or request.GET.get('action')
    ids = request.POST.getlist('ids[]') or request.GET.getlist('ids[]')

    if action not in ('unlock',):
        return JsonResponse({
            'status': 'error',
            'message': 'Unknown action.',
        }, status=400)

    if request.method != 'POST':
        return JsonResponse({
            'status': 'error',
            'message': 'This action requires POST.',
        }, status=405)

    if not request.user.can_edit_users:
        return JsonResponse({
            'status': 'error',
            'message': 'You do not have permission to unlock accounts.',
        }, status=403)

    valid_ids = []
    for record_id in ids:
        try:
            valid_ids.append(int(record_id))
        except (ValueError, TypeError):
            continue

    users = CustomUser.objects.filter(id__in=valid_ids, account_locked=True)

    unlocked = 0
    for user in users:
        user.unlock()
        unlocked += 1

    skipped = len(valid_ids) - unlocked

    return JsonResponse({
        'status': 'success',
        'message': (
            f'{unlocked} account(s) unlocked, '
            f'{skipped} skipped (not locked or not found).'
        ),
    })


def _selected_roleless(request, ids):
    """Resolve ids[] to accounts that are roleless right now.

    Returns (users, skipped). The requester's own account is never included,
    and neither is any account that is no longer roleless -- it gained a group
    or a role record since the page loaded, or is a superuser.
    """
    valid_ids = set()
    for record_id in ids:
        try:
            valid_ids.add(int(record_id))
        except (ValueError, TypeError):
            continue

    users = list(
        roleless_users()
        .filter(id__in=valid_ids)
        .exclude(pk=request.user.pk)
        .order_by('last_name', 'first_name')
    )
    return users, len(ids) - len(users)


def _delete_if_still_roleless(user, acting_user):
    """Delete `user` through user_deletion, re-checking is_roleless() first.

    The re-check and the delete share one transaction, with the account row
    locked, so a role granted between the preview and the confirm click is
    seen and the account kept. Returns True if deleted, False if it gained a
    role or is already gone; raises UserDeletionBlocked if preflight finds a
    blocker.
    """
    with transaction.atomic():
        user = CustomUser.objects.select_for_update().filter(pk=user.pk).first()
        if user is None or not is_roleless(user):
            return False
        user_deletion.delete_user(user, acting_user=acting_user)
    return True


def _roleless_complete(message):
    return JsonResponse({
        'outcome': 'call',
        'fn': 'onBulkActionComplete',
        'args': {'title': 'Done', 'message': message, 'status': 'success'},
    })


def do_roleless_bulk_action(request):
    """Bulk delete for the No Role tab of /ce/users/.

    Two steps, like the staff-account delete in cis.actions.user:

      preview_delete  read-only; a modal listing what deleting each selected
                      account would do (cis.services.user_deletion.preflight)
                      or why it is refused, with a confirm form.
      delete_account  posted by that form; deletes through
                      user_deletion.delete_user(), which reassigns authorship
                      to the requester, clears "assigned to" fields, writes a
                      deletion LogEntry, and refuses any blocker.

    Guard order matches do_locked_bulk_action: unknown action (400), then
    POST-only (405), then `can_edit_users` (403) -- the page gate is not
    enough for a permanent delete.

    Every account is re-checked twice: when the ids are resolved (only
    currently roleless accounts, never the requester's own) and again inside
    the delete transaction, so one that gained a role after the page or the
    preview loaded is skipped, never deleted.

    Responses use the ActionRegistry envelope (`modal` / `call`), so the
    tenant table JS dispatches through window.ActionRegistry.doBulkAction.
    """
    action = request.POST.get('action') or request.GET.get('action')

    if action not in ROLELESS_ACTIONS:
        return JsonResponse({
            'status': 'error',
            'message': 'Unknown action.',
        }, status=400)

    if request.method != 'POST':
        return JsonResponse({
            'status': 'error',
            'message': 'This action requires POST.',
        }, status=405)

    if not request.user.can_edit_users:
        return JsonResponse({
            'status': 'error',
            'message': 'You do not have permission to delete accounts.',
        }, status=403)

    users, skipped = _selected_roleless(request, request.POST.getlist('ids[]'))

    if action == 'preview_delete':
        plans = [user_deletion.preflight(user) for user in users]
        return JsonResponse({
            'outcome': 'modal',
            'html': render_to_string('cis/users/delete_preflight.html', {
                'plans': plans,
                'skipped': skipped,
                'skipped_note': 'your own account, or the account now has a role',
                'empty_note': ('None of the selected accounts can be deleted: '
                               'each is your own account or now has a role.'),
                'deletable_ids': [p.user.pk for p in plans if p.deletable],
                'bulk_actions_url': reverse('cis:roleless_users_bulk_action'),
                'confirm_action': 'delete_account',
                'form_id': 'roleless_delete_confirm',
                'strategy_verbs': {
                    user_deletion.REASSIGN: 'reassigned to you',
                    user_deletion.NULLIFY: 'cleared',
                    user_deletion.DELETE: 'removed',
                    'audit': 'removed (kept in the deletion log)',
                },
            }, request=request),
        })

    deleted = blocked = errored = 0
    for user in users:
        try:
            if _delete_if_still_roleless(user, request.user):
                deleted += 1
            else:
                skipped += 1
        except user_deletion.UserDeletionBlocked:
            blocked += 1
        except Exception:
            # delete_user() is atomic, so nothing is half-applied; keep going
            # so one bad row does not strand the rest of the selection.
            logger.exception('Unexpected error deleting roleless user %s', user.pk)
            errored += 1

    message = (
        f'{deleted} account(s) deleted, {blocked} blocked, {skipped} skipped '
        '(your own account, now holds a role, or not found).'
    )
    if errored:
        message += f' {errored} failed unexpectedly; see the server log.'
    return _roleless_complete(message)


def do_users_bulk_action(request):
    """Dispatch a /ce/users/ bulk action to cis.actions.user.

    Guard order matches do_locked_bulk_action: unknown action (400) before the
    POST-only check (405), so an unknown action arriving over GET can never
    reach a mutation. Authorization is the registry's job from there --
    `dispatch` enforces each action's declared permission, so an action stays
    refused even when the page never rendered its button.
    """
    action = request.POST.get('action') or request.GET.get('action')

    if action not in registered_slugs():
        return JsonResponse({
            'status': 'error',
            'message': 'Unknown action.',
        }, status=400)

    if request.method != 'POST':
        return JsonResponse({
            'status': 'error',
            'message': 'This action requires POST.',
        }, status=405)

    return user_actions.dispatch(request, action)


def get_password_reset_link(request):
    record_id = request.GET.get('id')
    record = get_object_or_404(CustomUser, pk=record_id)

    url = record.get_password_reset_link()

    return JsonResponse({
        'url': url})

def add_new(request):
    '''
    Add new page
    '''

    if not request.user.can_edit_users:
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger') 
        return redirect('cis:dashboard')

    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html'
    template = 'cis/users/add_new.html'

    if request.method == 'POST':
        form = UserForm(request.POST, user=request.user)

        existing = form.is_valid() and CustomUser.existing_by_username(
            form.cleaned_data['username'])

        if existing:
            # Never overwrite an account from here: an existing staff member
            # only gains the campuses ticked; anyone else is refused.
            if 'ce' not in existing.get_roles():
                form.add_error(
                    'username',
                    'This username belongs to an account that is not a staff account.')
            else:
                existing.add_process_campuses(form.cleaned_data['process_campus'])
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'This user already exists. The selected campus(es) were added to '
                    'their account; nothing else was changed.',
                    'list-group-item-success')
                return redirect('cis:user', record_id=existing.id)
        elif form.is_valid():
            try:
                user = CustomUser.add_new_staff(form)

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully saved record',
                    'list-group-item-success')
                return redirect('cis:user', record_id=user.id) #d
            except IntegrityError as intError:
                form._errors['email'] = ['Sorry, there was an error while adding user']
                print(intError)
        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = UserForm(user=request.user)

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax, 
            'page_title': "Add New",
            'labels': {
                'all_items': 'All Users'
            },
            'urls': {
                'add_new': 'cis:user_add_new',
                'all_items': 'cis:users'
            },
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'users', 'users')
        })

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    """
    Record details page
    """

    if not request.user.can_edit_users:
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger') 
        return redirect('cis:dashboard')

    template = 'cis/users/detail.html'
    record = get_object_or_404(CustomUser, pk=record_id)

    if request.method == 'POST':
        form = UserForm(request.POST, user=request.user, record=record)

        if form.is_valid():
            record.update(form)

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success') 
            return redirect('cis:user', record_id=record_id)
    else:
        campus = {}
        if record.campus:
            campus = record.campus

        form = UserForm(user=request.user, record=record, initial={
            'first_name':record.first_name,
            'last_name':record.last_name,
            'email':record.email,
            'username':record.username,
            'is_active':'Yes' if record.is_active else 'No',
            'process_campus': [str(pk) for pk in record.process_campuses.values_list('pk', flat=True)],
            'manage_settings': campus.get('manage_settings'),
            'manage_staff_accounts': campus.get('manage_staff_accounts'),
            'default_campus': campus.get('default_campus', ''),
        })

    return render(
        request,
        template, {
            'form': form,
            'page_title': "User",
            'history': Login.objects.filter(user=record).order_by('-date'),
            'labels': {
                'all_items': 'All Users'
            },
            'urls': {
                'add_new': 'cis:user_add_new',
                'all_items': 'cis:users'
            },
            'menu': draw_menu(cis_menu, 'users', 'users'),
            'record': record,
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'users', 'users')

    if not request.user.can_edit_users:
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger') 
        return redirect('cis:dashboard')

    template = 'cis/users/index.html'

    # Ordering, search and pagination are server-side in StaffUserViewSet now;
    # only the Excel export still needs a queryset on the page itself.
    if request.GET.get('export') == 'excel':
        return CustomUser.export_to_excel(
            CustomUser.objects.filter(groups__name='ce').order_by('-created_at'))

    return render(
        request,
        template,
        {
            'page_title': 'Users',
            'menu': menu,
            'urls': {
                'add_new': 'cis:user_add_new',
                'details': 'cis:user'
            },
            'users_table': build_users_table_config(
                variant='users_index',
                api_url='/ce/api/user?format=datatables',
                details_prefix='/ce/user/',
                filter_form_selector='#users_filter',
                # Buttons come from the registry, filtered by each action's
                # declared permission -- delete only appears for superusers.
                **_supported_kwargs(build_users_table_config, {
                    'bulk_actions': user_actions.for_scope('bulk', request.user),
                    'bulk_actions_url': reverse('cis:users_bulk_action'),
                }),
            ),
            # None when the tenant has not adopted the No Role tab yet; the
            # template then renders the staff table alone, as before.
            'roleless_users_table': _roleless_users_table_config(),
        })
