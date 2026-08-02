import logging

from django.shortcuts import render, get_object_or_404
from django.conf import settings
from django.contrib import messages, auth

from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.http import HttpResponseRedirect
from django.contrib.auth import logout

from cis.menu import cis_menu, draw_menu
from cis.models.teacher import Teacher
from cis.models.course import Course
from cis.models.term import Term

from cis.forms.highschool import HighSchoolOfferingLookupForm
from cis.forms.customuser import DemoRequestForm, MyCELoginForm

from cis.utils import (
    registration_terms, is_student_registration_open
)
from cis.models import section
from cis.landing_content import render_landing_body

logger = logging.getLogger(__name__)

import stripe
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

stripe.api_key = settings.STRIPE_SECRET_KEY


@csrf_exempt
def stripe_webhook(request):
    # PT-31: fail closed. Without a configured signing secret, signature
    # verification can be bypassed by an empty-key HMAC, so refuse to process
    # the event at all rather than reach construct_event / business logic.
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error(
            "STRIPE_WEBHOOK_SECRET is empty/unset; refusing to process webhook.")
        return HttpResponse(status=500)

    payload = request.body
    sig = request.META.get("HTTP_STRIPE_SIGNATURE")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    if event['type'] == 'payment_intent.succeeded':
        
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        from cis.models.student import Student
        from cis.models.term import Term
        from student_transactions.models import StudentTransaction

        student = get_object_or_404(Student, pk=metadata.get("student_id"))
        term = get_object_or_404(Term, pk=metadata.get("term_id"))

        transaction = StudentTransaction.objects.create(
            student=student,
            term=term,
            amount=float(session["amount_received"]) / 100,
            t_type='credit',
            label='cc',
            meta=session,
            description='Online Payment # {}'.format(session['id'])
        )
        transaction.save()
        try:
            transaction.send_payment_confirmation()
        except Exception as e:
            logger.error("Error sending payment confirmation: %s", e)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
    return HttpResponse(status=200)
stripe_webhook.login_required = False

def export_to_excel(request, model_type, parent):
    if model_type == "instructors_in_course":
        course = get_object_or_404(Course, pk=parent)
        return course.get_instructors_for_course(course, "excel")

    if model_type == "courses_for_instructor":
        record = get_object_or_404(Teacher, pk=parent)
        return record.get_course_certificates(return_type="excel")

def account_does_not_exist(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))

    messages.add_message(
                request,
                messages.SUCCESS,
                'Your credentials were correct but you do not have access to this system. If you think you should please contact our office.',
                'list-group-item-danger')
    return HttpResponseRedirect(reverse_lazy('index'))
account_does_not_exist.login_required = False

def index(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))

    if request.method == 'POST':
        form = HighSchoolOfferingLookupForm(request.POST)

        if form.is_valid():
            offerings = form.cleaned_data['highschool'].get_offered_classes(
                terms=Term.objects.filter(id__in=registration_terms())
            ).order_by('term', 'course')
        look_up_form = form
    else:
        offerings = None
        look_up_form = HighSchoolOfferingLookupForm()
    return render(request, 'cis/index/index.html', {
        'portal':settings.MY_CE,
        'offerings': offerings,
        'lookup_form': look_up_form})
index.login_required = False

def student_index(request):
    from cis.models.settings import Setting
    
    key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_cis_registrations"
    window_close_notice = Setting.get_value(key, "window_close_notice")
    
    form = MyCELoginForm(request)

    if request.method == 'POST':

        form = MyCELoginForm(
            request=request,
            data=request.POST
        )

        if not form.is_valid():
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please correct the errors and try again.',
                'list-group-item-danger'
            )
        else:
            form.save(request, 'student_index', 'logged_home')

    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))

    context = {
        'registration_terms': registration_terms(),
        'registration_is_open': is_student_registration_open(),
        'window_close_notice': window_close_notice,
        'form': form,
        'portal': settings.MY_CE,
    }
    context['page_body'] = render_landing_body(request, 'student', context)
    return render(request, 'cis/index/student.html', context)
student_index.login_required = False


def instructor_index(request):

    form = MyCELoginForm(request)

    if request.method == 'POST':

        form = MyCELoginForm(
            request=request,
            data=request.POST
        )

        if not form.is_valid():
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please correct the errors and try again.',
                'list-group-item-danger'
            )
        else:
            form.save(request, 'instructor_index', 'logged_home')

    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))

    try:
        from instructor_app.settings.inst_app_language import inst_app_language
    except ImportError:
        from instructor_app.instructor_app.settings.inst_app_language import inst_app_language
        
    app_settings = inst_app_language.from_db()
    accepting_applications = True if app_settings.get('is_accepting_new', 'No') == 'Yes' else False
    if not accepting_applications:
        closed_message = app_settings.get('closed_message', '-')
    else:
        closed_message = ''
    
    context = {
        'portal': settings.MY_CE,
        'form': form,
        'accepting_applications': accepting_applications,
        'closed_message': closed_message,
    }
    context['page_body'] = render_landing_body(request, 'instructor', context)
    return render(request, 'cis/index/instructor.html', context)
instructor_index.login_required = False


def highschool_facilitator_index(request):
    
    form = MyCELoginForm(request)

    if request.method == 'POST':

        form = MyCELoginForm(
            request=request,
            data=request.POST
        )

        if not form.is_valid():
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please correct the errors and try again.',
                'list-group-item-danger'
            )
        else:
            form.save(request, 'highschool_admin_index', 'logged_home')

    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))

    context = {'label': 'Facilitator', 'form': form, 'portal': settings.MY_CE}
    context['page_body'] = render_landing_body(request, 'counselor', context)
    return render(request, 'cis/index/highschool_admin.html', context)
highschool_facilitator_index.login_required = False

def highschool_admin_index(request):
    
    form = MyCELoginForm(request)

    if request.method == 'POST':

        form = MyCELoginForm(
            request=request,
            data=request.POST
        )

        if not form.is_valid():
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please correct the errors and try again.',
                'list-group-item-danger'
            )
        else:
            form.save(request, 'highschool_admin_index', 'logged_home')

    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))

    context = {'label': 'School Counselor or Administrator', 'form': form, 'portal': settings.MY_CE}
    context['page_body'] = render_landing_body(request, 'counselor', context)
    return render(request, 'cis/index/highschool_admin.html', context)
highschool_admin_index.login_required = False


def tech_center_staff_index(request):
    if request.method == 'POST':
        email = request.POST.get('useremail')
        password = request.POST.get('password')

        user = auth.authenticate(username=email, password=password)
        if not user:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Invalid email/password combination, please try again.',
                'list-group-item-danger')
            return HttpResponseRedirect(reverse_lazy('tech_center_staff_index'))

        if user is not None:
            if user.is_active:
                auth.login(request, user)

        return HttpResponseRedirect(reverse_lazy('logged_home'))

    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))

    return render(request, 'cis/index/tech_center_staff.html', {'label':'UMA Center Staff'})
tech_center_staff_index.login_required = False

def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
        messages.add_message(
            request,
            messages.SUCCESS,
            'Successfully logged out',
            'list-group-item-success')

    return HttpResponseRedirect(reverse_lazy('index'))
logout_view.login_required = False

def staff_index(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))
    
    if request.method == 'POST':
        email = request.POST.get('useremail')
        password = request.POST.get('password')

        user = auth.authenticate(username=email, password=password)
        if not user:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Invalid email/password combination, please try again.',
                'list-group-item-danger')
            return HttpResponseRedirect(reverse_lazy('instructor_index'))

        if user is not None:
            if user.is_active:
                auth.login(request, user)

        return HttpResponseRedirect(reverse_lazy('logged_home'))

    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))
    context = {'portal': settings.MY_CE, 'form': MyCELoginForm(request)}
    context['page_body'] = render_landing_body(request, 'staff', context)
    return render(request, 'cis/index/staff.html', context)
staff_index.login_required = False

def faculty_index(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))
    
    if request.method == 'POST':
        email = request.POST.get('useremail')
        password = request.POST.get('password')

        user = auth.authenticate(username=email, password=password)
        if not user:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Invalid email/password combination, please try again.',
                'list-group-item-danger')
            return HttpResponseRedirect(reverse_lazy('instructor_index'))

        if user is not None:
            if user.is_active:
                auth.login(request, user)

        return HttpResponseRedirect(reverse_lazy('logged_home'))

    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse_lazy('logged_home'))
    context = {'portal': settings.MY_CE, 'form': MyCELoginForm(request)}
    context['page_body'] = render_landing_body(request, 'faculty', context)
    return render(request, 'cis/index/faculty.html', context)
faculty_index.login_required = False

def dashboard(request):
    from cis.settings.registrations import registrations
    reg_settings = registrations.asHTML()

    from cis.views.password_management import cisForceSetPasswordForm
    set_password_form = cisForceSetPasswordForm
    form = set_password_form(request.user)

    if request.method == 'POST':
        form = cisForceSetPasswordForm(request.user, request.POST)
        if form.is_valid():
            form.save(request.user)
        else:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please fix the errors and try again.' + str(form.errors),
                'list-group-item-danger'
            )

    from cis.utils import active_term as get_active_term

    active_term = get_active_term()

    return render(
        request,
        'cis/dashboard.html',
        {
            'portal': settings.MY_CE,
            'reg_settings': reg_settings,
            'active_term': active_term,
            'access_requests_api_url': '/ce/api/hs-administrator-access-request',
            'registration_summary_api_url': '/ce/api/registration-summary/?term_id=-2&format=datatables',
            'form': form,
            'menu': draw_menu(cis_menu, 'dashboard')})


def logged_home(request):
    roles = request.user.get_roles()

    user_roles = []
    for key, val in settings.MY_CE['roles'].items():
        if key in roles:
            user_roles.append(val)

    if len(user_roles) == 1:
        print(user_roles)
        return HttpResponseRedirect(reverse_lazy(user_roles[0]['url']))

    # get roles for user
    return render(
        request,
        'cis/index/logged_home.html',
        {
            'portal': settings.MY_CE,
            'roles': user_roles
        })


def submit_new_request(request):
    """
    Handle new request submission in the frontend
    """
    template = 'cis/index/demo_request.html'
    context = {}
    if request.method == 'POST':
        form = DemoRequestForm(request.POST)

        if form.is_valid():
            record = form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                'Thank you for submitting your request. We will be in touch with you soon.',
                'list-group-item-success'
            )
            return redirect('index')
    else:
        form = DemoRequestForm()

    context['form'] = form
    return render(request, template, context)
submit_new_request.login_required = False


def lockout(request, credentials, *args, **kwargs):

    messages.add_message(
        request,
        messages.SUCCESS,
        'You have been locked out of the system due to too many failed login attempts. Please try again later.',
        'list-group-item-danger'
    )

    return render(request, 'cis/index/index.html', {
        'portal':settings.MY_CE
    })
lockout.login_required = False