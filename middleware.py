from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from threading import current_thread

class CspReportOnlyMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        resp = self.get_response(request)
        resp["Content-Security-Policy-Report-Only"] = (
            "default-src 'self'; "
            "script-src 'self' https://js.stripe.com; "
            "frame-src 'self' https://js.stripe.com https://checkout.stripe.com; "
            "connect-src 'self' https://api.stripe.com; "
            "img-src 'self' data: https://*.stripe.com; "
            "style-src 'self' 'unsafe-inline' https://*.stripe.com; "
            "font-src 'self' data: https://js.stripe.com"
        )
        return resp
    
class LoginRequiredMiddleware(MiddlewareMixin):

    def process_view(self, request, view_func, view_args, view_kwargs):

        if view_func.__name__ in [
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
        ]:
            return None


        if not getattr(view_func, 'login_required', True):
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