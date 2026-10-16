"""CE action: link an instructor / HS administrator record to an existing account.

GET shows the email form; POST with only `email` shows a confirmation of the
account found; POST with `confirm` performs the relink. See
cis.services.relink_role_user for what moves and what stays.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin

from cis.models.highschool_administrator import HSAdministrator
from cis.models.teacher import Teacher
from cis.services.relink_role_user import (
    HS_ADMIN_RELINK, INSTRUCTOR_RELINK, RelinkError, check_relink,
    find_target, relink,
)


def _relink_view(request, policy, record, detail_url_name, page_title):
    detail_url = reverse(detail_url_name, kwargs={'record_id': record.pk})
    context = {
        'record': record,
        'policy': policy,
        'detail_url': detail_url,
        'page_title': page_title,
        'email': '',
        'target': None,
        'error': None,
    }

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        context['email'] = email
        target = find_target(email)
        try:
            check_relink(policy, record, target)
        except RelinkError as e:
            context['error'] = str(e)
        else:
            if request.POST.get('confirm'):
                try:
                    old_user = relink(policy, record, target, request.user)
                except RelinkError as e:
                    context['error'] = str(e)
                else:
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        f'Linked to {target.email}. The previous account '
                        f'({old_user.email}) no longer has the {policy.label} role.',
                        'list-group-item-success')
                    return redirect(detail_url)
            context['target'] = target
            context['target_roles'] = target.get_roles()

    return render(request, 'cis/relink_user.html', context)


@xframe_options_sameorigin
def relink_instructor_user(request, record_id):
    record = get_object_or_404(Teacher.objects.select_related('user'), pk=record_id)
    return _relink_view(
        request, INSTRUCTOR_RELINK, record, 'cis:instructor',
        'Change Linked Account')


@xframe_options_sameorigin
def relink_hs_admin_user(request, record_id):
    record = get_object_or_404(HSAdministrator.objects.select_related('user'), pk=record_id)
    return _relink_view(
        request, HS_ADMIN_RELINK, record, 'cis:hs_admin',
        'Change Linked Account')
