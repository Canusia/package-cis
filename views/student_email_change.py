"""
Student portal: verified self-service email change (#79, from nnu#15 / ewu#80).

cis ships the view; the tenant mounts it in its own ``student`` URLconf and
wraps it in its own portal gates, because those gates (``user_has_student_role``,
``verify_account_complete``) live in the tenant's ``student`` app, which cis
must not import::

    # student/urls.py (tenant)
    from cis.views.student_email_change import change_email
    path('change_email/',
         user_passes_test(user_has_student_role, login_url='/')(
             verify_account_complete(change_email)),
         name='change_email'),

URL contract: the view redirects back to whatever name it was mounted under
(``request.resolver_match.view_name``) and, on success, to ``profile_url_name``
(default ``student:profile``). Template contract: the page extends
``base_template`` (default ``student/base_student.html``) and includes
``student/partials/_breadcrumb.html``, the same student-portal templates
package-grades' student pages rely on. Both are view kwargs, so a tenant with a
different portal layout passes its own through ``path(..., kwargs={...})``.

The "Change email" link on the profile page stays tenant-owned (the profile
template is the tenant's); hide it when ``is_locked(student)``.
"""
from django.contrib import messages
from django.shortcuts import render, redirect

from cis.forms.student_email_change import NewEmailForm, VerifyCodeForm
from cis.menu import draw_menu, STUDENT_MENU
from cis.models.email_change import EmailChangeRequest
from cis.models.student import Student
from cis.services.student_email_change import (
    EmailChangeError, LOCKED_MESSAGE, is_locked,
    start_email_change, resend_code, confirm_email_change,
)
from cis.settings.student_email_change import get_config

SESSION_KEY = 'email_change_request_id'
DEFAULT_BASE_TEMPLATE = 'student/base_student.html'
DEFAULT_PROFILE_URL_NAME = 'student:profile'


def _pending_request(request, student):
    req_id = request.session.get(SESSION_KEY)
    if not req_id:
        return None
    req = EmailChangeRequest.objects.filter(
        pk=req_id, student=student, status=EmailChangeRequest.PENDING
    ).first()
    if req is None:
        request.session.pop(SESSION_KEY, None)
    return req


def _msg(request, level, text, css):
    messages.add_message(request, level, text, css)


def change_email(request, base_template=DEFAULT_BASE_TEMPLATE,
                 profile_url_name=DEFAULT_PROFILE_URL_NAME):
    # Fail closed even if a tenant forgets its portal gate: only a logged-in
    # user with a student record gets this page.
    if not request.user.is_authenticated:
        return redirect('/')
    student = Student.objects.filter(user_id=request.user.pk).select_related('user').first()
    if student is None:
        return redirect('/')

    self_url_name = request.resolver_match.view_name
    locked = is_locked(student)
    pending = _pending_request(request, student)
    email_form = NewEmailForm()
    code_form = VerifyCodeForm()

    if request.method == 'POST' and locked:
        _msg(request, messages.ERROR, LOCKED_MESSAGE, 'list-group-item-danger')
        return redirect(self_url_name)

    if request.method == 'POST':
        if 'cancel' in request.POST:
            if pending:
                pending.status = EmailChangeRequest.CANCELLED
                pending.save(update_fields=['status'])
            request.session.pop(SESSION_KEY, None)
            return redirect(self_url_name)

        if 'request_code' in request.POST:
            email_form = NewEmailForm(request.POST, user=request.user)
            if email_form.is_valid():
                try:
                    req = start_email_change(student, email_form.cleaned_data['new_email'])
                except EmailChangeError as e:
                    email_form.add_error('new_email', str(e))
                else:
                    request.session[SESSION_KEY] = str(req.id)
                    _msg(request, messages.SUCCESS,
                         f'We sent a verification code to {req.new_email}.', 'list-group-item-success')
                    return redirect(self_url_name)

        elif 'resend_code' in request.POST and pending:
            try:
                resend_code(pending)
                _msg(request, messages.SUCCESS, 'A new code has been sent.', 'list-group-item-success')
            except EmailChangeError as e:
                _msg(request, messages.ERROR, str(e), 'list-group-item-danger')
            return redirect(self_url_name)

        elif 'verify_code' in request.POST and pending:
            code_form = VerifyCodeForm(request.POST)
            if code_form.is_valid():
                try:
                    confirm_email_change(pending, code_form.cleaned_data['code'], actor=request.user)
                except EmailChangeError as e:
                    code_form.add_error('code', str(e))
                else:
                    request.session.pop(SESSION_KEY, None)
                    _msg(request, messages.SUCCESS,
                         f'Your email has been changed to {pending.new_email}. Use it the next time you log in.',
                         'list-group-item-success')
                    return redirect(profile_url_name)

        elif ('resend_code' in request.POST or 'verify_code' in request.POST) and not pending:
            _msg(request, messages.ERROR,
                 'Your email change request is no longer active. Please start again.',
                 'list-group-item-danger')
            return redirect(self_url_name)

    return render(request, 'cis/student/change_email.html', {
        'base_template': base_template,
        'profile_url_name': profile_url_name,
        'student': student,
        'locked': locked,
        'locked_message': LOCKED_MESSAGE,
        'max_attempts': get_config()['max_attempts'],
        'pending': pending,
        'email_form': email_form,
        'code_form': code_form,
        'menu': draw_menu(STUDENT_MENU, 'profile', '', 'student'),
    })
