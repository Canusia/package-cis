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
