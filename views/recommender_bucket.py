"""Recommender buckets: add / edit / delete, shared by the CE high school
Recommenders tab and the HS-admin Personnel page.

The ``*_response`` functions do the work and return ActionRegistry JSON; each
portal wraps them with its own permission check and URL names (see
``CE_URLS`` here and highschool_admin's personnel views).
"""
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import escape

from cis.forms.recommender_bucket import RecommenderBucketForm
from cis.highschool_scope import scope_highschools
from cis.models.highschool import HighSchool
from cis.models.recommender_bucket import RecommenderBucket
from cis.utils import user_has_cis_role

CE_URLS = {
    'add': 'cis:recommender_bucket_add',
    'edit': 'cis:recommender_bucket_edit',
    'delete': 'cis:recommender_bucket_delete',
}


def panel_context(highschool, can_manage, urls):
    """Context for cis/highschools/recommender_buckets/_panel.html."""
    from django.db.models import Prefetch
    from cis.models.highschool_administrator import HSAdministratorPosition
    from cis.services.recommender_scope import coverage

    buckets = list(highschool.recommender_buckets.prefetch_related(Prefetch(
        'positions', queryset=HSAdministratorPosition.objects.select_related(
            'hsadmin__user').order_by('hsadmin__user__last_name'))))
    return {
        'highschool': highschool,
        'buckets': buckets,
        'coverage': coverage(highschool),
        'can_manage': can_manage,
        'urls': urls,
    }


def _done(title, message):
    return JsonResponse({'outcome': 'call', 'fn': 'reloadRecommenderBuckets',
                         'args': {'title': title, 'message': message}})


def _modal(template, context, request):
    return JsonResponse({'outcome': 'modal',
                         'html': render_to_string(template, context, request=request)})


def _form_error(form):
    return JsonResponse({'message': 'Please correct the errors and try again.',
                         'errors': form.errors.as_json()}, status=400)


def _forbidden():
    return JsonResponse(
        {'status': 'error', 'message': 'You do not have permission to do that.'}, status=403)


def bucket_form_response(request, highschool, action_url, bucket=None):
    """Modal (first POST) or save (apply=1) for a new or existing bucket."""
    if request.method != 'POST':
        return _forbidden()
    if request.POST.get('apply') != '1':
        return _modal('cis/highschools/recommender_buckets/_form.html', {
            'title': 'Edit Recommender Bucket' if bucket else 'Add Recommender Bucket',
            'form': RecommenderBucketForm(instance=bucket, highschool=highschool),
            'form_action': action_url, 'highschool': highschool,
        }, request)

    form = RecommenderBucketForm(request.POST, instance=bucket, highschool=highschool)
    if not form.is_valid():
        return _form_error(form)
    saved = form.save(request.user)
    return _done('Bucket saved', f'Saved {saved.name} ({saved.range_label}) for {highschool.name}.')


def bucket_delete_response(request, bucket, action_url):
    """Confirmation modal naming who becomes unranged, then delete."""
    from cis.models.note import HighSchoolNote

    if request.method != 'POST':
        return _forbidden()
    if request.POST.get('apply') != '1':
        from django.db.models import Count
        unranged = [str(p.hsadmin) for p in bucket.positions.select_related(
            'hsadmin__user').annotate(n=Count('recommender_buckets')) if p.n == 1]
        return _modal('cis/highschools/recommender_buckets/_delete.html', {
            'bucket': bucket, 'unranged': unranged, 'form_action': action_url,
        }, request)

    highschool, label = bucket.highschool, f'{bucket.name} ({bucket.range_label})'
    with transaction.atomic():
        bucket.positions.clear()
        bucket.delete()
        HighSchoolNote.objects.create(
            highschool=highschool, createdby=request.user,
            note=f'Removed recommender bucket {escape(label)}.')  # notes render as HTML
    return _done('Bucket removed', f'Removed {label} from {highschool.name}.')


# -- CE ----------------------------------------------------------------------

def _ce_highschool(request, record_id):
    return get_object_or_404(
        scope_highschools(HighSchool.objects.all(), user=request.user), pk=record_id)


def ce_can_manage(user, highschool):
    """Buckets scope the school's counselors on every campus, so (as for
    deleting the school) the user must be able to manage each campus link."""
    from cis.highschool_scope import can_manage_link
    return all(can_manage_link(user, link.campus)
               for link in highschool.campus_links.select_related('campus'))


def _ce_bucket(request, bucket_id):
    return get_object_or_404(
        RecommenderBucket.objects.select_related('highschool'), pk=bucket_id,
        highschool__in=scope_highschools(HighSchool.objects.all(), user=request.user))


def ce_bucket_add(request, record_id):
    if not user_has_cis_role(request.user):
        return _forbidden()
    highschool = _ce_highschool(request, record_id)
    if not ce_can_manage(request.user, highschool):
        return _forbidden()
    return bucket_form_response(
        request, highschool, str(reverse(CE_URLS['add'], args=[highschool.id])))


def ce_bucket_edit(request, bucket_id):
    if not user_has_cis_role(request.user):
        return _forbidden()
    bucket = _ce_bucket(request, bucket_id)
    if not ce_can_manage(request.user, bucket.highschool):
        return _forbidden()
    return bucket_form_response(
        request, bucket.highschool, str(reverse(CE_URLS['edit'], args=[bucket.id])), bucket)


def ce_bucket_delete(request, bucket_id):
    if not user_has_cis_role(request.user):
        return _forbidden()
    bucket = _ce_bucket(request, bucket_id)
    if not ce_can_manage(request.user, bucket.highschool):
        return _forbidden()
    return bucket_delete_response(
        request, bucket, str(reverse(CE_URLS['delete'], args=[bucket.id])))
