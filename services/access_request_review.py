"""Review of high-school admin access requests (approve / deny + email).

Placeholders the CE review form and the access-request Settings templates
may use. One catalogue, enforced by cis.validators.validate_email_placeholders
on the server and mirrored by staticfiles/cis/js/access_request_review.js.
"""
import re

APPROVE = 'approve'
DENY = 'deny'

_COMMON = {
    'name': "The requester's name",
    'email': "The requester's email address",
    'highschool': 'The high school they asked to administer',
    'role': 'The position/title they asked for',
}

PLACEHOLDERS = {
    APPROVE: {**_COMMON,
              'password_reset_link': 'The link they use to set their password'},
    DENY: dict(_COMMON),
}

ALL_PLACEHOLDERS = set(PLACEHOLDERS[APPROVE]) | set(PLACEHOLDERS[DENY])

RESET_LINK_RE = re.compile(r'{{\s*password_reset_link\s*}}')

MISSING_RESET_LINK = (
    'Approval emails must include {{password_reset_link}} so the user can '
    'set their password.')

import logging
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.template import Context, Template
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

logger = logging.getLogger(__name__)

NOTE_RESET_LINK = '[password reset link]'


@dataclass
class ReviewOutcome:
    decision: str
    email_sent: bool = False
    note_saved: bool = False
    role_already_existed: bool = False
    note_url: Optional[str] = None


def _existing_admin(record):
    from cis.models.highschool_administrator import HSAdministrator
    return HSAdministrator.objects.filter(user__email__iexact=record.email).first()


def note_location(record):
    """(label, url) of where this request's decision note lives, or None."""
    if record.status == 'Submitted':
        return None
    admin = _existing_admin(record)
    if admin is not None:
        return (f'{admin} (Notes tab)', reverse('cis:hs_admin', args=[admin.pk]))
    return (record.highschool.name, reverse('cis:hs_detail', args=[record.highschool.pk]))


def current_role_permissions(record):
    """Names of the permissions the approved role holds now, or None."""
    from cis.models.highschool_administrator import (
        ANY_CAMPUS, HSAdministratorPosition, hsadmin_permission_objects,
    )
    if record.status != 'Approved':
        return None
    role = HSAdministratorPosition.objects.filter(
        hsadmin__user__email__iexact=record.email,
        highschool=record.highschool,
        position__name__iexact=record.role,
    ).first()
    if role is None:
        return None
    return list(hsadmin_permission_objects(role.codenames(ANY_CAMPUS))
                .values_list('name', flat=True))


def _note_text(record, user, decision, form, email_sent):
    data = form.cleaned_data
    verb = 'approved' if decision == APPROVE else 'denied'
    who = escape(user.get_full_name() or user.email)
    when = timezone.localtime().strftime('%m/%d/%Y %I:%M %p')
    lines = [
        f'Access request <strong>{verb}</strong> by {who} on {when} &mdash; '
        f'{escape(record.role)} at {escape(record.highschool.name)}.'
    ]
    if decision == APPROVE:
        perms = [p.name for p in data.get('permissions') or []]
        scope = data.get('scope')
        lines.append(
            f'Permissions ({escape(scope.name) if scope else "All campuses"}): '
            f'{escape(", ".join(perms)) if perms else "none"}')
    context = Context(record.email_context(reset_link=NOTE_RESET_LINK))
    subject = Template(data['email_subject']).render(context)
    body = Template(data['email_message']).render(context)
    status = 'Email sent' if email_sent else 'Email was not sent (sending failed)'
    lines.append(f'{status} to {escape(record.email)}.<br>'
                 f'<strong>Subject:</strong> {escape(subject)}<br>{body}')
    return '<br><br>'.join(lines)


def _write_note(record, user, text):
    from cis.models.note import HSAdministratorNote
    admin = _existing_admin(record)
    if admin is not None:
        HSAdministratorNote.objects.create(hsadmin=admin, createdby=user, note=text)
    else:
        record.highschool.add_note(user, text)


def complete_review(form, user):
    """Apply a valid decision submit of AccessRequestReviewForm.

    Saves details + status (and on approval the account/role) atomically,
    then emails the requester, then records a note. A failed email or note
    never undoes the decision; the outcome says what happened.
    """
    data = form.cleaned_data
    decision = data['decision']
    outcome = ReviewOutcome(decision=decision)

    with transaction.atomic():
        record = form.save(commit=False)
        record.status = 'Approved' if decision == APPROVE else 'Denied'
        record.save()
        if decision == APPROVE:
            outcome.role_already_existed = not record.grant_access(data)

    try:
        outcome.email_sent = bool(record.send_email(
            subject=data['email_subject'], body=data['email_message']))
    except Exception:
        logger.exception('Access request %s: email failed', record.pk)

    try:
        _write_note(record, user, _note_text(record, user, decision, form, outcome.email_sent))
        outcome.note_saved = True
        location = note_location(record)
        outcome.note_url = location[1] if location else None
    except Exception:
        logger.exception('Access request %s: note failed', record.pk)

    return outcome
