"""CE "High School Uploads" tab on /ce/students/support_docs/ (#56).

Every school's HighSchoolTranscript rows, filterable by term, school and
review state, with Mark Reviewed / Mark Not Reviewed bulk actions.
"""
from django.http import JsonResponse
from django.urls import reverse

from cis.actions.hs_uploads import BULK, hs_upload_actions, registered_slugs
from cis.services.table_configs import get_table_config

API_URL = '/ce/api/highschool-transcript/?format=datatables'


def _table_config(user):
    """The tenant's table config, or None if it doesn't ship one yet.

    Resolved here, not at import time: a module-level get_table_config() is a
    bare import, and a tenant lagging on myce_tenant_configs would lose the
    whole cis URLconf instead of just this table (system check cis.W003).
    """
    try:
        module = get_table_config('hs_uploads_table')
    except ImportError:
        return None
    return module.build_config(
        variant='hs_uploads_index',
        api_url=API_URL,
        filter_form_selector='#hs_uploads_filter',
        bulk_actions=hs_upload_actions.for_scope(BULK, user),
        bulk_actions_url=reverse('cis:hs_uploads_bulk_action'),
    )


def tab_context(request):
    """Context for the tab, merged into the support_docs page."""
    from cis.models.highschool import HighSchool, HighSchoolTranscript
    from cis.utils import active_term

    context = {
        'hs_uploads_table': _table_config(request.user),
        'hs_uploads_highschools': HighSchool.objects.filter(
            highschooltranscript__isnull=False).distinct().order_by('name'),
        'hs_uploads_active_term': active_term(),
    }
    if context['hs_uploads_table'] is None:
        context['hs_uploads_records'] = HighSchoolTranscript.objects.select_related(
            'highschool', 'term', 'uploaded_by').order_by('-uploaded_on')[:200]
    return context


def do_bulk_action(request):
    """Unknown action (400) before the POST-only check (405), as in
    do_users_bulk_action; the registry then enforces each action's permission."""
    action = request.POST.get('action') or request.GET.get('action')
    if action not in registered_slugs():
        return JsonResponse({'status': 'error', 'message': 'Unknown action.'}, status=400)
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'error', 'message': 'This action requires POST.'}, status=405)
    return hs_upload_actions.dispatch(request, action)
