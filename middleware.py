from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from threading import current_thread

# The policy CspReportOnlyMiddleware reports against. A tenant that pays
# through another gateway (nnu: Authorize.net) sets CSP_REPORT_ONLY_POLICY to
# its own string (#114 item 4).
DEFAULT_CSP_REPORT_ONLY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://js.stripe.com; "
    "frame-src 'self' https://js.stripe.com https://checkout.stripe.com; "
    "connect-src 'self' https://api.stripe.com; "
    "img-src 'self' data: https://*.stripe.com; "
    "style-src 'self' 'unsafe-inline' https://*.stripe.com; "
    "font-src 'self' data: https://js.stripe.com"
)


class CspReportOnlyMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        from django.conf import settings
        resp = self.get_response(request)
        resp["Content-Security-Policy-Report-Only"] = getattr(
            settings, 'CSP_REPORT_ONLY_POLICY', DEFAULT_CSP_REPORT_ONLY_POLICY)
        return resp


# View (function or class) names LoginRequiredMiddleware lets through without
# a login. A tenant adds its own with settings.LOGIN_EXEMPT_VIEWS (#92), or
# marks a view with @login_exempt.
DEFAULT_LOGIN_EXEMPT_VIEWS = (
    'index',
    '<lambda>',
    'login',
    '',
    'view',
    'metadata',
    'acs',
    'slo',
    'logout',
    'TokenCreateView',
    'StudentSISAPI',
    'StudentIDViewSet',
    'create_checkout_session',
    'ClassSectionViewSet',
    'ClassRegistrationSISViewSet',
    'RegistrationViewSet',
    'TermViewSet',
    'StudentTransactionViewSet',
    'FacultySectionRequestViewSet',
    'CETicketViewSet',
    'StudentTicketViewSet',
    'InstructorTicketViewSet',
    'HSAdminTicketViewSet',
    'TicketSummaryViewSet',
)


def login_exempt(view):
    """Let ``view`` (a function, or a class-based view / viewset class)
    through LoginRequiredMiddleware. The view does its own authentication."""
    view.login_required = False
    return view


def login_exempt_view_names():
    from django.conf import settings
    return set(DEFAULT_LOGIN_EXEMPT_VIEWS) | set(
        getattr(settings, 'LOGIN_EXEMPT_VIEWS', ()))


class LoginRequiredMiddleware(MiddlewareMixin):

    def process_view(self, request, view_func, view_args, view_kwargs):

        if view_func.__name__ in login_exempt_view_names():
            return None


        if not getattr(view_func, 'login_required', True):
            return None
        # as_view() functions don't carry class attributes; check the class.
        view_class = getattr(view_func, 'cls', None) or getattr(view_func, 'view_class', None)
        if not getattr(view_class, 'login_required', True):
            return None

        if not request.user.is_authenticated:
            messages.add_message(
                request,
                messages.SUCCESS,
                """You need to be logged in to access this resource. 
                Please select your role and login to continue""",
                'list-group-item-danger')
        return login_required(view_func, login_url='/')(request, *view_args, **view_kwargs)


_requests = {}


def current_request():
    return _requests.get(current_thread().ident, None)


class RequestMiddleware(MiddlewareMixin):

    def process_request(self, request):
        _requests[current_thread().ident] = request

    def process_response(self, request, response):
        # when response is ready, request should be flushed
        _requests.pop(current_thread().ident, None)
        return response


    def process_exception(self, request, exception):
        # if an exception has happened, request should be flushed too
         _requests.pop(current_thread().ident, None)

class CampusMiddleware:
    """Serve each request as one campus (MC-02 #26, MC-03 #27).

    Multi-campus mode: the host resolves through django.contrib.sites to the
    Campus linked by Campus.site. request.site and request.campus are set and
    the request runs inside campus_context(). An unknown host is a 400 -- a
    default campus would show one college's data on the other's host. A CE
    staff member whose process_campuses lacks the host's campus is refused
    with a 403; superusers pass. Other roles have no process_campuses and are
    scoped by their records instead, so they are not checked here.

    Single-campus mode: request.campus is the deployment's campus and nothing
    is refused. Place after AuthenticationMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.http import HttpResponseBadRequest
        from cis.campus_context import (
            campus_context, current_campus_or_none, is_multi_campus)

        if not is_multi_campus():
            request.campus = current_campus_or_none()
            with campus_context(request.campus):
                return self.get_response(request)

        from cis.models.course import Campus
        host = request.get_host().split(':')[0].lower()
        campus = (Campus.objects.select_related('site')
                  .filter(site__domain__iexact=host).first())
        if campus is None:
            return HttpResponseBadRequest('This host is not assigned to a campus.')

        request.site = campus.site
        request.campus = campus
        refused = self._refuse_other_campus_staff(request, campus)
        if refused is not None:
            return refused
        with campus_context(campus):
            return self.get_response(request)

    @staticmethod
    def _refuse_other_campus_staff(request, campus):
        from django.http import HttpResponseForbidden
        from cis.campus_gate import get_process_campus_ids
        from cis.utils import user_has_cis_role

        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated or user.is_superuser:
            return None
        if not user_has_cis_role(user):
            return None
        if str(campus.id) in get_process_campus_ids(user):
            return None
        return HttpResponseForbidden('You do not have access to this campus.')
