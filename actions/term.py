"""Host-side term actions (registered on the shared term_actions registry)."""
import importlib.util

from django.db import IntegrityError
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse

from cis.forms.term import BulkAssignParentForm
from cis.models.term import Term
from myce.component_registry.term import term_actions

if importlib.util.find_spec('ethos.ethos'):
    from ethos.ethos.library.ethos import Ethos
else:
    from ethos.library.ethos import Ethos


def _subterm_dates(period):
    dates = {}
    if period.get('startOn'):
        dates['start'] = period['startOn']
    if period.get('endOn'):
        dates['end'] = period['endOn']
    return dates


def _fetch_subterms(term):
    """Fetch this term's direct sub-term academic periods from the SIS."""
    parent_guid = str(term.external_sis_id)
    periods = Ethos().get_child_academic_periods(parent_guid, depth=2)
    return [
        p for p in periods
        if p.get('category', {}).get('type') == 'subterm'
        and p.get('category', {}).get('parent', {}).get('id') == parent_guid
    ]


def _upsert_subterms(term, subterms):
    """Create/update the given SIS sub-term periods as child Terms of `term`.

    Returns (created, updated, skipped). Skips a period whose (academic_year,
    label) already belongs to a different SIS record, or whose reparent would
    form a cycle, or that collides with the unique constraint.
    """
    created, updated, skipped = 0, 0, 0
    for p in subterms:
        guid = p.get('id')
        label = p.get('title') or p.get('code')
        record = Term.objects.filter(external_sis_id=guid).first()
        if record is None:
            fallback = Term.objects.filter(
                academic_year=term.academic_year, label=label).first()
            # A different SIS period already owns this (academic_year, label):
            # do not silently overwrite its external_sis_id / parent / meta.
            if (fallback is not None
                    and fallback.external_sis_id
                    and str(fallback.external_sis_id) != str(guid)):
                skipped += 1
                continue
            record = fallback

        # Never repoint an existing term in a way that forms a cycle.
        if record is not None and record.pk and record.would_create_cycle(term):
            skipped += 1
            continue

        is_new = record is None
        if is_new:
            record = Term(academic_year=term.academic_year, label=label)
        record.code = p.get('code', '')
        record.external_sis_id = guid
        record.parent = term
        record.academic_year = term.academic_year
        record.meta = p
        record.dates = {**(record.dates or {}), **_subterm_dates(p)}
        try:
            record.save()
        except IntegrityError:
            skipped += 1
            continue
        if is_new:
            created += 1
        else:
            updated += 1
    return created, updated, skipped


@term_actions.action('sis', label='Pull & Create Sub-Terms from SIS',
                     icon='fa fa-sitemap', scope=['detail'])
def pull_sub_terms(request):
    ids = request.POST.getlist('ids[]')
    term_id = ids[0] if ids else request.POST.get('record_id')
    try:
        term = Term.objects.get(pk=term_id)
    except Term.DoesNotExist:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'Sub-Terms', 'message': 'Term not found.'},
                            status=404)

    if not term.external_sis_id:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'Sub-Terms',
                             'message': "This term isn't linked to the SIS."})

    # Re-fetch from the SIS on every request (server-authoritative — the confirm
    # step never trusts client-submitted period data, only the chosen GUIDs).
    subterms = _fetch_subterms(term)

    if request.POST.get('action_confirmed'):
        selected = set(request.POST.getlist('subterm_ids[]'))
        chosen = [p for p in subterms if str(p.get('id')) in selected]
        created, updated, skipped = _upsert_subterms(term, chosen)
        message = f'{created} created, {updated} updated'
        if skipped:
            message += f', {skipped} skipped (conflicts)'
        message += '.'
        return JsonResponse({'outcome': 'alert', 'status': 'success',
                             'title': 'Sub-Terms', 'message': message})

    if not subterms:
        return JsonResponse({'outcome': 'alert', 'status': 'info',
                             'title': 'Sub-Terms',
                             'message': 'No sub-terms found for this term in the SIS.'})

    linked = set(str(g) for g in Term.objects.filter(
        external_sis_id__in=[p.get('id') for p in subterms]
    ).values_list('external_sis_id', flat=True))
    candidates = [{
        'guid': p.get('id'),
        'code': p.get('code', ''),
        'label': p.get('title') or p.get('code'),
        'exists': str(p.get('id')) in linked,
    } for p in subterms]

    html = render_to_string('cis/term/pull_subterms_modal.html', {
        'title': 'Pull & Create Sub-Terms',
        'form_action': reverse('cis:term_bulk_actions'),
        'term': term,
        'candidates': candidates,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})


@term_actions.action('sis', label='Look up SIS ID by Code',
                     icon='fa fa-search', scope=['detail'])
def lookup_sis_id(request):
    ids = request.POST.getlist('ids[]')
    term_id = ids[0] if ids else request.POST.get('record_id')
    try:
        term = Term.objects.get(pk=term_id)
    except Term.DoesNotExist:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'SIS Lookup', 'message': 'Term not found.'},
                            status=404)

    if not term.code:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'SIS Lookup',
                             'message': 'This term has no code to look up.'})

    guid = Ethos().get_academic_period_id(term.code)
    if not guid:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'SIS Lookup',
                             'message': f"No SIS academic period found for code "
                                        f"'{term.code}'."})

    term.external_sis_id = guid
    term.save(update_fields=['external_sis_id'])
    return JsonResponse({'outcome': 'alert', 'status': 'success',
                         'title': 'SIS Lookup',
                         'message': f"Linked term to SIS academic period {guid}."})


@term_actions.action('parent', label='Assign Parent Term',
                     icon='fa fa-sitemap', scope=['index'])
def assign_parent(request):
    ids = request.POST.getlist('ids[]')

    if request.POST.get('action_confirmed'):
        form = BulkAssignParentForm(ids, data=request.POST)
        if form.is_valid():
            assigned, skipped = form.save()
            msg = f'{assigned} assigned'
            if skipped:
                msg += f', {skipped} skipped (self/cycle)'
            return JsonResponse({'outcome': 'call', 'fn': 'onBulkActionComplete',
                                 'args': {'message': msg + '.', 'status': 'success'}})
        return JsonResponse({'message': 'Please correct the errors and try again.',
                             'errors': form.errors.as_json()}, status=400)

    form = BulkAssignParentForm(ids)
    html = render_to_string('cis/term/assign_parent_modal.html', {
        'title': 'Assign Parent Term',
        'form': form,
        'form_action': reverse('cis:term_bulk_actions'),
        'action_slug': 'assign_parent',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})
