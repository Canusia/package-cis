"""
Verified self-service email change for students (#79, from nnu#15 / ewu#80).

Flow: start_email_change() -> code emailed to new address ->
confirm_email_change() -> user.email/username updated, private note,
confirmation emailed to old + new address.
"""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template import Context, Template
from django.template.loader import get_template
from django.utils import timezone, dateformat

from mailer import send_html_mail

from cis.models.customuser import CustomUser
from cis.models.email_change import EmailChangeRequest
from cis.settings.student_email_change import get_config

LOCKED_MESSAGE = 'Your application is under review, so your email cannot be changed right now.'


class EmailChangeError(Exception):
    pass


def is_locked(student):
    return student.application_status == 'in_review'


def _ensure_not_locked(student):
    if is_locked(student):
        raise EmailChangeError(LOCKED_MESSAGE)


def _limits(conf):
    return {'ttl_minutes': conf['code_ttl_minutes'], 'max_attempts': conf['max_attempts']}


def _send(subject, message_template, context, to):
    text_body = Template(message_template).render(Context(context))
    html_body = get_template('cis/email.html').render({'message': text_body})
    send_html_mail(subject, text_body, html_body, settings.DEFAULT_FROM_EMAIL, to)


def email_in_use(email, exclude_user_id=None):
    email = email.strip().lower()
    qs = CustomUser.objects.filter(
        Q(email__iexact=email) | Q(username__iexact=email) | Q(secondary_email__iexact=email)
    )
    if exclude_user_id:
        qs = qs.exclude(pk=exclude_user_id)
    return qs.exists()


def _send_code(req, code, conf):
    user = req.student.user
    _send(
        conf['verification_subject'],
        conf['verification_message'],
        {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'new_email': req.new_email,
            'code': code,
            'expires_minutes': conf['code_ttl_minutes'],
        },
        [req.new_email],
    )


def _check_rate_limit(student, conf):
    recent = EmailChangeRequest.objects.filter(student=student)
    last = recent.order_by('-sent_at').first()
    if last is not None and not last.can_resend(conf['resend_cooldown_seconds']):
        raise EmailChangeError('Please wait a moment before requesting another code.')
    window_start = timezone.now() - timedelta(hours=24)
    if recent.filter(created_at__gte=window_start).count() >= conf['max_requests_per_day']:
        raise EmailChangeError(
            'You have reached the limit for email change requests today. Please try again tomorrow.')


def start_email_change(student, new_email):
    _ensure_not_locked(student)
    new_email = new_email.strip().lower()
    if new_email == (student.user.email or '').lower():
        raise EmailChangeError('That is already your current email address.')
    if email_in_use(new_email, exclude_user_id=student.user.pk):
        raise EmailChangeError('This email is already registered in the system.')

    conf = get_config()
    _check_rate_limit(student, conf)
    req, code = EmailChangeRequest.objects.create_for(student, new_email, **_limits(conf))
    _send_code(req, code, conf)
    return req


def resend_code(req):
    _ensure_not_locked(req.student)
    if req.status != EmailChangeRequest.PENDING:
        raise EmailChangeError('This request is no longer active. Please start again.')
    conf = get_config()
    if not req.can_resend(conf['resend_cooldown_seconds']):
        raise EmailChangeError('Please wait a moment before requesting another code.')
    code = req.regenerate_code(ttl_minutes=conf['code_ttl_minutes'])
    _send_code(req, code, conf)


def confirm_email_change(req, code, actor):
    _ensure_not_locked(req.student)
    if req.status != EmailChangeRequest.PENDING:
        raise EmailChangeError('This request is no longer active. Please start again.')
    if req.is_expired:
        raise EmailChangeError('This code has expired. Please request a new one.')
    if req.attempts_remaining <= 0:
        raise EmailChangeError('Too many incorrect attempts. Please request a new code.')
    if not req.check_code(code):
        raise EmailChangeError('The code you entered is incorrect.')

    student = req.student
    changed_on = timezone.localtime()

    with transaction.atomic():
        locked_req = EmailChangeRequest.objects.select_for_update().get(pk=req.pk)
        if locked_req.status != EmailChangeRequest.PENDING:
            raise EmailChangeError('This request is no longer active. Please start again.')

        user = CustomUser.objects.select_for_update().get(pk=student.user.pk)
        if email_in_use(req.new_email, exclude_user_id=user.pk):
            raise EmailChangeError('This email is already registered in the system.')

        old_email = user.email
        user.email = req.new_email
        user.username = req.new_email
        try:
            user.save()
        except IntegrityError:
            raise EmailChangeError('This email is already registered in the system.')

        # Same review flag StudentProfileForm.save sets on student self-edits:
        # surfaces the student in CE's "Profile Changed" list so the new
        # address can be updated in the SIS/Slate.
        student.profile_dirty_at = changed_on
        student.save(update_fields=['profile_dirty_at'])

        req.old_email = old_email
        req.status = EmailChangeRequest.COMPLETED
        req.completed_at = changed_on
        req.save(update_fields=['old_email', 'status', 'completed_at'])

        student.add_note(
            createdby=actor,
            note=f'Student changed account email from {old_email} to {req.new_email} (verified by code).',
            meta={'type': 'private'},
        )

        conf = get_config()
        context = {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'old_email': old_email,
            'new_email': req.new_email,
            'changed_on': dateformat.format(changed_on, 'F j, Y g:i A'),
        }
        recipients = [old_email, req.new_email]

        def _send_confirmations():
            for addr in recipients:
                _send(conf['confirmation_subject'], conf['confirmation_message'], context, [addr])

        transaction.on_commit(_send_confirmations)
