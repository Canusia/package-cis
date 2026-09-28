"""Bulk actions for the CE High School Uploads tab (#56).

Registered on a cis-owned ActionRegistry, as cis/actions/user.py explains:
no tenant ships a host registry for this page, and cis/urls.py imports the
view on every deployment. Each action declares its permission, which the
registry enforces both when rendering the buttons and at dispatch.
"""
import uuid

from django.http import JsonResponse

from myce.component_registry import ActionRegistry

from cis.utils import user_has_cis_role

hs_upload_actions = ActionRegistry()

BULK = 'bulk'
GROUP = 'review'


def can_review(user):
    return bool(user and user.is_authenticated and user_has_cis_role(user))


def registered_slugs():
    slugs = set()
    for group in hs_upload_actions.for_scope(BULK).values():
        slugs.update(group['actions'])
    return slugs


def selected_uploads(request):
    """ids[] -> HighSchoolTranscript rows; malformed or unknown ids are skipped."""
    from cis.models.highschool import HighSchoolTranscript
    ids = []
    for raw in request.POST.getlist('ids[]'):
        try:
            ids.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    return HighSchoolTranscript.objects.filter(pk__in=ids)


def _complete(message):
    return JsonResponse({
        'outcome': 'call',
        'fn': 'onBulkActionComplete',
        'args': {'title': 'Done', 'message': message, 'status': 'success'},
    })


@hs_upload_actions.action(
    GROUP, slug='mark_hs_uploads_reviewed', label='Mark Reviewed', scope=[BULK],
    icon='fas fa-check', btn_class='btn-primary', permission=can_review)
def mark_reviewed(request):
    count = 0
    for record in selected_uploads(request).filter(reviewed_on__isnull=True):
        record.mark_reviewed(request.user)
        count += 1
    return _complete(f'{count} upload(s) marked reviewed.')


@hs_upload_actions.action(
    GROUP, slug='mark_hs_uploads_not_reviewed', label='Mark Not Reviewed',
    scope=[BULK], icon='fas fa-undo', btn_class='btn-secondary',
    confirm='Mark the selected upload(s) as not reviewed?', permission=can_review)
def mark_not_reviewed(request):
    count = 0
    for record in selected_uploads(request).filter(reviewed_on__isnull=False):
        record.mark_not_reviewed()
        count += 1
    return _complete(f'{count} upload(s) marked not reviewed.')
