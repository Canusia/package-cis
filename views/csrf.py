"""CSRF_FAILURE_VIEW for MyCE tenants (package-cis#52).

Enable with ``CSRF_FAILURE_VIEW = 'cis.views.csrf.csrf_failure'`` and route the
``cis.views.csrf`` logger to a handler that reaches the pod logs at WARNING.
"""
import logging

from django.conf import settings
from django.shortcuts import render

logger = logging.getLogger(__name__)


def csrf_failure(request, reason=''):
    """
    Log why the CSRF check failed -- Django's own django.security.csrf warning
    is dropped when DEBUG is off -- and show a friendly retry page instead of
    the bare 403.
    """
    logger.warning(
        'CSRF failure: reason=%r path=%s method=%s has_csrf_cookie=%s '
        'has_session_cookie=%s origin=%r referer=%r user_agent=%r',
        reason,
        request.path,
        request.method,
        settings.CSRF_COOKIE_NAME in request.COOKIES,
        settings.SESSION_COOKIE_NAME in request.COOKIES,
        request.META.get('HTTP_ORIGIN'),
        request.META.get('HTTP_REFERER'),
        request.META.get('HTTP_USER_AGENT'),
    )

    return render(
        request,
        'cis/csrf_failure.html',
        {'retry_url': request.get_full_path()},
        status=403,
    )
csrf_failure.login_required = False
