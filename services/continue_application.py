"""Continue-application links: a way back into Complete Signup for a student
who verified their email but left before finishing.

A link carries a token built like Django's password-reset token: an HMAC over
the student's state plus a timestamp. It is valid for CONTINUE_LINK_MAX_AGE
and stops working on its own once the student finishes signup, because
finishing stores a password and a psid, both of which feed the hash. No model
field is needed.

The views that accept the link live in each tenant's ``student`` app; this
module is the shared part: the token, the "can this student continue?" rule,
and the email.
"""
import logging
from datetime import timedelta

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int

logger = logging.getLogger(__name__)

CONTINUE_LINK_MAX_AGE = timedelta(days=3)

DEFAULT_SUBJECT = 'Continue your application'
DEFAULT_EMAIL = (
    '<p>Hello {{student_first_name}},</p>'
    '<p>Use this link to continue your application: '
    '<a href="{{continue_link}}">{{continue_link}}</a></p>'
    '<p>The link works for {{expires_in_days}} days.</p>'
)


class ContinueApplicationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = 'cis.services.continue_application.ContinueApplicationTokenGenerator'

    def _make_hash_value(self, student, timestamp):
        user = student.user
        return (f'{student.pk}{user.password}{user.psid or ""}'
                f'{student.account_verified}{timestamp}')

    def check_token(self, student, token):
        """Like PasswordResetTokenGenerator.check_token, with our own max age."""
        if not (student and token):
            return False
        try:
            ts_b36, _hash = token.split('-')
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False
        expected = self._make_token_with_timestamp(student, ts, self.secret)
        if not constant_time_compare(expected, token):
            return False
        age = self._num_seconds(self._now()) - ts
        return 0 <= age <= CONTINUE_LINK_MAX_AGE.total_seconds()


token_generator = ContinueApplicationTokenGenerator()


def can_continue(student):
    """Verified, but signup never finished: no password stored and no real SIS id.

    `not user.password` rather than has_usable_password(): the signup form
    never calls set_password, so the column is empty, and Django reads empty
    as *usable*. '-' counts as no id because complete_signup stamps it
    alongside the password.
    """
    user = student.user
    return (bool(student.account_verified)
            and not user.password
            and user.psid in ('', '-', None))


def make_token(student):
    return token_generator.make_token(student)


def check_token(student, token):
    return can_continue(student) and token_generator.check_token(student, token)


def make_link(student):
    """Absolute URL of the student's continue link (the tenant's student app)."""
    from django.urls import reverse
    from cis.utils import getDomain
    return getDomain() + reverse(
        'student:continue_application',
        kwargs={'student_id': student.id, 'token': make_token(student)})


def send_link(student, sent_by=None):
    """Email the continue link. Returns True when sent.

    Best effort, like the verification re-sends: a failure is logged and
    returns False rather than raising into the page that asked.
    """
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template import Context, Template
    from django.template.loader import get_template

    from cis.settings.registration_email import registration_email

    try:
        email_settings = registration_email.from_db() or {}
        subject = email_settings.get('continue_link_subject') or DEFAULT_SUBJECT
        body = email_settings.get('continue_link_email') or DEFAULT_EMAIL
        text_body = Template(body).render(Context({
            'student_first_name': student.user.first_name,
            'student_last_name': student.user.last_name,
            'continue_link': make_link(student),
            'expires_in_days': CONTINUE_LINK_MAX_AGE.days,
        }))
        if getattr(settings, 'DEBUG', False):
            # Never email real students from a dev box; the link goes to the log.
            logger.warning('DEBUG: continue link for student %s (not emailed): %s',
                           student.id, make_link(student))
            student.add_note(sent_by, 'Continue application link logged (DEBUG, not emailed)')
            return True
        message = EmailMultiAlternatives(
            subject, text_body, getattr(settings, 'DEFAULT_FROM'), [student.user.email])
        message.attach_alternative(
            get_template('cis/email.html').render({'message': text_body}), 'text/html')
        message.send()
    except Exception:
        logger.exception('Could not send the continue link to student %s', student.id)
        return False

    student.add_note(sent_by, 'Sent continue application link')
    return True
