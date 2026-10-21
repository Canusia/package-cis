"""Consortiums: the high school Consortiums tab's membership actions and the
/ce/consortiums/ master page.

Membership actions follow the Campuses tab (views/highschool.py
highschool_campus_*): two-step ActionRegistry posts, where the first POST
returns the modal and the modal's form posts back with apply=1.
"""
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.urls import reverse

from cis.forms.consortium import ConsortiumForm, ConsortiumMembershipForm
from cis.highschool_scope import scope_highschools
from cis.menu import cis_menu, draw_menu
from cis.models.consortium import Consortium, ConsortiumMembership
from cis.models.highschool import HighSchool
from cis.utils import user_has_cis_role
from cis.views.highschool import _forbidden, _form_error


def _membership_done(title, message):
    return JsonResponse({
        'outcome': 'call',
        'fn': 'reloadHighschoolConsortiums',
        'args': {'title': title, 'message': message},
    })


def _modal(template, context, request):
    return JsonResponse({
        'outcome': 'modal',
        'html': render_to_string(template, context, request=request),
    })


def membership_add(request, record_id):
    """Add a high school to an existing consortium, or to a new one."""
    if not user_has_cis_role(request.user):
        return _forbidden()
    record = get_object_or_404(
        scope_highschools(HighSchool.objects.all(), user=request.user), pk=record_id)
    action_url = str(reverse('cis:highschool_consortium_add', args=[record.id]))

    if request.POST.get('apply') != '1':
        return _modal('cis/highschools/consortium_membership_form.html', {
            'title': 'Add to Consortium', 'form': ConsortiumMembershipForm(highschool=record),
            'form_action': action_url, 'submit_label': 'Add', 'record': record,
        }, request)

    form = ConsortiumMembershipForm(request.POST, highschool=record)
    if not form.is_valid():
        return _form_error(form)
    membership = form.save_or_error()
    if membership is None:
        return _form_error(form)
    return _membership_done(
        'Added to consortium',
        'Added %s to %s.' % (record.name, membership.consortium.name))


def _get_manageable_membership(request, membership_id):
    """(membership, None) when the user may act on it, else (None, response)."""
    if not user_has_cis_role(request.user):
        return None, _forbidden()
    membership = get_object_or_404(
        ConsortiumMembership.objects.select_related('consortium', 'highschool'),
        pk=membership_id,
        highschool__in=scope_highschools(HighSchool.objects.all(), user=request.user))
    return membership, None


def membership_edit(request, membership_id):
    """Edit a membership's status, joined date and billing basis."""
    membership, denied = _get_manageable_membership(request, membership_id)
    if denied:
        return denied
    action_url = str(reverse('cis:consortium_membership_edit', args=[membership.id]))

    if request.POST.get('apply') != '1':
        return _modal('cis/highschools/consortium_membership_form.html', {
            'title': 'Edit Consortium Membership',
            'form': ConsortiumMembershipForm(instance=membership),
            'form_action': action_url, 'submit_label': 'Save',
            'record': membership.highschool, 'membership': membership,
        }, request)

    form = ConsortiumMembershipForm(request.POST, instance=membership)
    if not form.is_valid():
        return _form_error(form)
    if form.save_or_error() is None:
        return _form_error(form)
    return _membership_done(
        'Membership updated',
        'Updated %s in %s.' % (membership.highschool.name, membership.consortium.name))


def membership_delete(request, membership_id):
    """Remove a high school from a consortium (confirmation modal, then delete)."""
    membership, denied = _get_manageable_membership(request, membership_id)
    if denied:
        return denied

    if request.POST.get('apply') != '1':
        return _modal('cis/highschools/consortium_membership_delete.html', {
            'title': 'Remove From Consortium', 'membership': membership,
            'form_action': str(reverse('cis:consortium_membership_delete',
                                       args=[membership.id])),
        }, request)

    highschool_name, consortium_name = membership.highschool.name, membership.consortium.name
    membership.delete()
    return _membership_done(
        'Removed from consortium',
        'Removed %s from %s.' % (highschool_name, consortium_name))


# -- /ce/consortiums/ master page ---------------------------------------------

def _consortiums_done(title, message):
    return JsonResponse({
        'outcome': 'call',
        'fn': 'reloadConsortiums',
        'args': {'title': title, 'message': message},
    })


def index(request):
    """All consortiums with their Active member counts."""
    if not user_has_cis_role(request.user):
        return _forbidden()
    records = Consortium.objects.annotate(
        member_count=Count('memberships', filter=Q(memberships__status='Active')),
    ).order_by('name')
    return render(request, 'cis/consortiums/index.html', {
        'page_title': 'Consortiums',
        'records': records,
        'menu': draw_menu(cis_menu, 'highschools', 'consortiums'),
    })


def detail(request, record_id):
    """A consortium and its member schools."""
    if not user_has_cis_role(request.user):
        return _forbidden()
    record = get_object_or_404(
        Consortium.objects.prefetch_related(Prefetch(
            'memberships',
            queryset=ConsortiumMembership.objects.select_related('highschool')
            .order_by('highschool__name'))),
        pk=record_id)
    return render(request, 'cis/consortiums/detail.html', {
        'page_title': record.name,
        'record': record,
        'menu': draw_menu(cis_menu, 'highschools', 'consortiums'),
    })


def _consortium_form_view(request, record=None):
    if not user_has_cis_role(request.user):
        return _forbidden()
    if record is None:
        action_url, title, label = str(reverse('cis:consortium_add')), 'Add Consortium', 'Add'
    else:
        action_url = str(reverse('cis:consortium_edit', args=[record.id]))
        title, label = 'Edit Consortium', 'Save'

    if request.POST.get('apply') != '1':
        return _modal('cis/consortiums/form.html', {
            'title': title, 'form': ConsortiumForm(instance=record),
            'form_action': action_url, 'submit_label': label,
        }, request)

    form = ConsortiumForm(request.POST, instance=record)
    if not form.is_valid():
        return _form_error(form)
    saved = form.save()
    return _consortiums_done(
        'Consortium saved', 'Saved %s.' % saved.name)


def consortium_add(request):
    return _consortium_form_view(request)


def consortium_edit(request, record_id):
    if not user_has_cis_role(request.user):
        return _forbidden()
    return _consortium_form_view(request, get_object_or_404(Consortium, pk=record_id))
