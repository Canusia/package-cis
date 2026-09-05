"""
Registration Views
"""
import json
import logging
import uuid

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from django.utils.safestring import mark_safe
from django.http import JsonResponse, HttpResponse
from django.template.context_processors import csrf
from django.views.decorators.clickjacking import xframe_options_exempt

from django.template.loader import get_template, render_to_string
from crispy_forms.utils import render_crispy_form
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cis.models.section import StudentRegistration
from cis.models.student import Student, StudentCampusID, StudentAgreement, StudentRecommendation, ParentConsent
from cis.models.term import Term
from cis.models.course import Campus

from cis.utils import (
    registration_terms, active_term, YES_NO_OPTIONS, get_default_campus,
    can_edit_campus_registration,
    upload_to_s3,
    CIS_student_only,
    FACULTY_user_only,
    INSTRUCTOR_user_only,
    CIS_user_only,
    user_has_cis_role,
    user_has_faculty_role,
    user_has_instructor_role,
)
from cis.campus_gate import scope_queryset_by_campus, campus_gate, get_accessible_campuses, processable_ids
from cis.menu import cis_menu, draw_menu
from cis.services.table_configs import get_table_config
from cis.services.tenant_services import get_tenant_service
build_registrations_table_config = get_table_config('registrations_table').build_config
from cis.settings.registrations import RegistrationForm
from cis.forms.section import (
    AddNewStudentRegistrationForm,
    StudentRegistrationChangeStatusForm
)
from ..forms.student import (
    StudentCampusIDForm
)

from ..serializers.registration import StudentRegistrationSerializer

from myce.component_registry.registration import registration_tabs, registration_actions

from cis.views.eager import (
    eager_queryset,
    with_registration_related,
)

logger = logging.getLogger(__name__)


def _valid_registration_id(value):
    """Return `value` if it parses as a UUID, else None.

    StudentRegistration.id is a UUIDField, so handing a malformed string to
    get_object_or_404 raises ValidationError ('... is not a valid UUID') and
    surfaces as a 500 rather than a 404. Same guard style as the viewset
    filters above.
    """
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
    return value


@eager_queryset(with_registration_related)
class RegistrationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentRegistrationSerializer
    permission_classes = [CIS_user_only | FACULTY_user_only | INSTRUCTOR_user_only]

    def get_queryset(self):
        term = self.request.GET.get('term', str(active_term().id)).strip()

        if term == '' or term == '-1':
            term = str(active_term().id)

        if term == '-3':
            term = None
            
        campus = self.request.GET.get('campus', '').strip()
        status = self.request.GET.get('status', '').strip()
        registration_term_code = self.request.GET.get('registration_term_code', '').strip()

        record_type = self.request.GET.get('record_type', '').strip()

        signed_student_agreement = self.request.GET.get('signed_student_agreement', '').strip()
        signed_parent_consent = self.request.GET.get('signed_parent_consent', '').strip()

        student = self.request.GET.get('student', '').strip()
        class_section = self.request.GET.get('class_section', '').strip()
        needs_mirroring = self.request.GET.get('needs_mirroring')

        records = StudentRegistration.objects.filter().all()

        if registration_term_code:
            records = records.filter(
                class_section__registration_term__code=registration_term_code
            )
            term = None
            
        if record_type:
            if record_type == 'with_prereq':
                
                records = records.filter(
                    Q(class_section__course__prereq=None) |
                    Q(class_section__course__prereq='')
                )

            if record_type == 'needs_mirroring':
                records = records.filter(
                    needs_mirroring=True
                )
 
        if student:
            # PT-fuzz: `student` feeds a UUIDField lookup (Student.id).
            # Reject a present-but-malformed value before it reaches the DB,
            # which would otherwise raise django.core.exceptions.ValidationError
            # ('... is not a valid UUID') -> HTTP 500. An unrecognized id
            # genuinely matches no rows, so return an empty set.
            try:
                uuid.UUID(str(student))
            except (ValueError, AttributeError, TypeError):
                return StudentRegistration.objects.none()
            records = records.filter(student__id=student)
        elif class_section:
            # PT-fuzz: same class as `student` (ClassSection.id is a UUIDField).
            try:
                uuid.UUID(str(class_section))
            except (ValueError, AttributeError, TypeError):
                return StudentRegistration.objects.none()
            records = records.filter(class_section__id=class_section)
        elif term:
            if term == '-2':
                records = records.filter(
                    class_section__term__in=registration_terms()
                )
            else:
                # PT-fuzz: the sentinels ''/-1/-2/-3 are already normalized
                # above; anything else reaching here is treated as a real
                # Term UUID. A non-sentinel non-UUID (e.g. a term *code*)
                # must not 500 -> empty set.
                try:
                    uuid.UUID(str(term))
                except (ValueError, AttributeError, TypeError):
                    return StudentRegistration.objects.none()
                records = records.filter(class_section__term__id=term)

        if status:
            records = records.filter(status=status)
        
        if needs_mirroring:
            needs_mirroring = bool(needs_mirroring)
            records = records.filter(needs_mirroring=needs_mirroring)

        if signed_student_agreement:
            # get students who have a signed consent for 
            # - term
            # - student            
            signed_pconsent = StudentAgreement.objects.filter()
            if term == '-2':
                signed_pconsent = signed_pconsent.filter(
                    term__in=registration_terms()
                )
            elif term:
                signed_pconsent = signed_pconsent.filter(
                    term__id=term
                )

            if signed_student_agreement == '1':
                records = records.filter(
                    student__id__in=signed_pconsent.values_list(
                        'student__id', flat=True
                    )
                )
            else:
                records = records.exclude(
                    student__id__in=signed_pconsent.values_list(
                        'student__id', flat=True
                    )
                )

        if signed_parent_consent:
            # get students who have a signed consent for 
            # - term
            # - student
            signed_pconsent = ParentConsent.objects.filter()
            if term == '-2':
                signed_pconsent = signed_pconsent.filter(
                    term__in=registration_terms()
                )
            elif term:
                signed_pconsent = signed_pconsent.filter(
                    term__id=term
                )

            if signed_parent_consent == '1':
                records = records.filter(
                    student__id__in=signed_pconsent.values_list(
                        'student__id', flat=True
                    )
                )
            else:
                records = records.exclude(
                    student__id__in=signed_pconsent.values_list(
                        'student__id', flat=True
                    )
                )

        # Object-level scoping (PT-14, revised): /ce/api/registration is limited
        # by permission_classes to CE (ce), faculty, and instructor callers.
        # CE staff are additionally campus-scoped (campus resolved via
        # class_section -> course -> campus); faculty see all; an instructor
        # sees only registrations for sections they teach. Because this is a
        # ReadOnlyModelViewSet, scoping get_queryset also governs retrieve(),
        # so an out-of-scope detail lookup returns 404. highschool admins are
        # handled by the separate /highschool_admin/api/registration endpoint
        # and are not permitted here. Mirrors the PT-4 StudentViewSet gate.
        user = self.request.user

        # Campus for a registration is resolved via class_section -> course ->
        # campus. Apply the user-selected dropdown filter (if any), then the
        # ce-staff security scope on the same path (a no-op for non-ce roles).
        if campus and campus != '-1':
            try:
                uuid.UUID(str(campus))
                records = records.filter(class_section__course__campus__id=campus)
            except (ValueError, AttributeError, TypeError):
                pass

        records = scope_queryset_by_campus(
            records, user, campus_path='class_section__course__campus')
        if user_has_cis_role(user) or user_has_faculty_role(user):
            return records
        if user_has_instructor_role(user):
            return records.filter(class_section__teacher__user=user)
        return records.none()

@campus_gate(StudentRegistration, campus_of=lambda r: r.class_section.course.campus, mode='json')
def delete(request, record_id):
    record = get_object_or_404(StudentRegistration, pk=record_id)

    if can_edit_campus_registration(request.user, record):
        note_text = f'Deleted registration for {record.class_section} in {record.status}'

        record.delete()
        record.student.add_note(request.user, note_text)
        
        data = {
            'status':'success',
            'message':'Success removed registration',
        }
    else:
        data = {
            'status':'error',
            'message':'You do not have permission to delete this registration',
        }
    return JsonResponse(data)


def manage_registration(request):
    """
    Change registration status or delete registration
    """
    # PT-42: this view is dispatched from cis.views.ajax.add_new on the
    # model == 'studentregistration' branch. In ewu, /ce/add_new_ajax/ is
    # shared across role portals and is NOT URL-gated, so a highschool_admin
    # session can reach this method directly. The `refresh_registration_form`
    # action renders AddNewStudentRegistrationForm, whose Term / HighSchool /
    # ClassSection querysets are unscoped and leak cross-tenant metadata.
    # This per-method CIS guard is the sole defense (covers GET + every POST
    # action), mirroring the PT-8 / PT-23 per-branch guards in cis.views.ajax.
    if not user_has_cis_role(request.user):
        return JsonResponse({
            'status': 'error',
            'message': 'You are not authorized to perform this action.',
        }, status=403)

    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/students/edit_registration.html'

    if request.method == 'POST':
        if request.POST.get('action') == 'delete_registration':
            # EditStudentRegistration now takes the registration it edits as its
            # first positional argument, and this branch only ever used the form
            # to pull `id` out of the POST. Read the id directly, and gate on
            # campus + write the audit note the way delete() above does.
            registration_id = _valid_registration_id(request.POST.get('id'))
            if registration_id is None:
                return JsonResponse({
                    'status': 'error',
                    'message': 'There was an error while completing the request',
                })

            registration = get_object_or_404(StudentRegistration, pk=registration_id)

            if not can_edit_campus_registration(request.user, registration):
                return JsonResponse({
                    'status': 'error',
                    'message': 'You do not have permission to delete this registration',
                }, status=403)

            student = registration.student
            note_text = (
                f'Deleted registration for {registration.class_section} '
                f'in {registration.status}'
            )
            registration.delete()
            student.add_note(request.user, note_text)

            return JsonResponse({
                'status': 'status',
                'message': 'Success',
            })

        """
        Refresh add new registration form when term or high school is changed
        """
        if request.POST.get('action') == 'refresh_registration_form':
            form = AddNewStudentRegistrationForm(initial=request.POST)

            ctx = {}
            ctx.update(csrf(request))
            form_html = render_crispy_form(form, context=ctx)

            data = {
                'status':'status',
                'form_html':form_html,
            }
            return JsonResponse(data)

        """
        Add New Registration
        """
        if request.POST.get('action') == 'add_new_registration':
            form = AddNewStudentRegistrationForm(data=request.POST)

            if form.is_valid():
                student_registration = StudentRegistration()
                student_registration.student = Student.objects.get(pk=form.cleaned_data['student'])
                student_registration.term = form.cleaned_data['term']
                student_registration.highschool = form.cleaned_data['highschool']
                student_registration.class_section = form.cleaned_data['class_section']
                student_registration.status = form.cleaned_data['status']

                student_registration.save()

                data = {
                    'status':'success',
                    'message':'Successfully completed your request'
                }
                return JsonResponse(data)

            ctx = {}
            ctx.update(csrf(request))
            form_html = render_crispy_form(form, context=ctx)

            data = {
                'status':'error',
                'form_html':form_html,
                'message':'There was an error while completing your request. Please try again'
            }
            return JsonResponse(data)

        """
        Edit student registration status
        """
        # The form needs the registration it is editing, so resolve it from the
        # POST before binding. The write goes through form.save() rather than
        # assigning .status directly, so the audit notes the form writes (grade
        # change on class_section + student, verification status) actually fire.
        registration_id = _valid_registration_id(request.POST.get('id'))
        if registration_id is None:
            return JsonResponse({
                'status': 'error',
                'message': 'There was an error while completing the request',
            })

        registration = get_object_or_404(StudentRegistration, pk=registration_id)

        if not can_edit_campus_registration(request.user, registration):
            return JsonResponse({
                'status': 'error',
                'message': 'You do not have permission to edit this registration',
            }, status=403)

        form = get_tenant_service('registration_form').EditStudentRegistration(
            registration, request.POST)
        if form.is_valid():
            registration = form.save(request, registration)

            data = {
                'status':'success',
                'message':'Successfully saved record',
                'new_record_id':registration.id,
                'new_record_name':'',
                'action': 'reload'
            }
            return JsonResponse(data)
    else:
        registration_id = _valid_registration_id(request.GET.get('id'))
        if registration_id is None:
            get_object_or_404(StudentRegistration, pk=uuid.uuid4())

        registration = get_object_or_404(StudentRegistration, pk=registration_id)
        if not str(registration.student.id) == request.GET.get('parent'):
            get_object_or_404(Student, -1)

        # The form seeds id / status / grade / verification_status / pay_type
        # and the rest from the record itself, so the old `initial={...}` dict
        # was both redundant and missing the now-required positional argument.
        form = get_tenant_service('registration_form').EditStudentRegistration(registration)

    return render(
        request,
        template, {
            'form': form,
            'record': registration,
            'ajax': ajax,
            'base_template': base_template
        })

def tab(request, record_id, tab_slug):
    """Render a single Registration detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(StudentRegistration, pk=record_id)
    return registration_tabs.render_tab(request, record, tab_slug)


@campus_gate(StudentRegistration, campus_of=lambda r: r.class_section.course.campus, mode='page')
@xframe_options_exempt
def detail(request, record_id):
    """
    Record details page
    """
    template = 'cis/registrations/detail.html'
    record = get_object_or_404(StudentRegistration, pk=record_id)

    form = get_tenant_service('registration_form').EditStudentRegistration(record)

    student_id_form = StudentCampusIDForm(
        initial={
            'id': '-1',
            'student_id': record.student.id
        }
    )

    if request.method == 'POST':
        if request.POST.get('action') == 'edit_campus':
            student_id_form = StudentCampusIDForm(request.POST)

            if student_id_form.is_valid():
                try:
                    student_id = student_id_form.save()
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Successfully saved campus id',
                        'list-group-item-success')
                except Exception as e:
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Unable to save campus id - ' + str(e),
                        'list-group-item-danger')
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Unable to complete request. Please correct the error(s) below and try again.',
                    'list-group-item-danger')

        elif can_edit_campus_registration(request.user, record):
            form = get_tenant_service('registration_form').EditStudentRegistration(record, request.POST)

            if form.is_valid():
                try:
                    record = form.save(request, record)

                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Successfully updated registration',
                        'list-group-item-success')
                except Exception as e:
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Unable to update registration - ' + str(e),
                        'list-group-item-warning')
                return redirect('cis:registration', record_id=record_id)
        else:
            messages.add_message(
                request,
                messages.SUCCESS,
                'You do not have permission to edit registration for this campus',
                'list-group-item-warning')

    def _tab_url(record_id):
        def url_for(slug):
            return reverse('cis:registration_tab', args=[record_id, slug])
        return url_for

    all_tabs = registration_tabs.for_record(
        request, record,
        url_for=_tab_url(record.id))
    left_tabs  = {s: t for s, t in all_tabs.items() if t['order'] < 20}
    right_tabs = {s: t for s, t in all_tabs.items() if t['order'] >= 20}

    return render(
        request,
        template, {
            'menu': draw_menu(cis_menu, 'students', 'registrations'),
            'page_title': "Student Registration",
            'record': record,
            'left_tabs': left_tabs,
            'right_tabs': right_tabs,
            'terms': Term.objects.all(),
            'campus': Campus.get_all(),
            'detail_actions': registration_actions.for_scope('detail', request.user),
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'students', 'registrations')
    template = 'cis/registrations/index.html'

    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'Registrations',
            'api_url': '/ce/api/registration?format=datatables',
            'registrations_table': build_registrations_table_config(
                variant='registration_index',
                api_url='/ce/api/registration?format=datatables',
                # The filter form lives in the template outside the partial,
                # so we leave filter_form_html empty but still tell the JS where to attach.
                filter_form_selector='#class_section_filter',
            ),
            'active_term': active_term(),
            'campus': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'terms': Term.objects.all().order_by('-academic_year__name'),
            'registration_status': StudentRegistration.STATUS_OPTIONS,
            'yes_no': YES_NO_OPTIONS
        }
    )

def do_bulk_action(request):
    action = request.GET.get('action')

    if request.method == 'POST':
        action = request.POST.get('action')
        
    if action == 'change_status':
        return manage_registration_status(request)

    if action == 'change_class_section':
        return manage_class_section_change(request)

    if action == 'send_to_sis':
        return send_to_sis(request)

    if action == 'set_needs_mirroring':
        return manage_needs_mirroring(request)

    if action == 'submit_drop_request':
        return manage_drop_request(request)

    return registration_actions.dispatch(request, action)


def manage_drop_request(request):
    template = 'cis/registrations/update_status.html'
    import importlib

    if importlib.util.find_spec('drop_wd.drop_wd'):
        from drop_wd.drop_wd.forms import CEDropRequestForm
    else:
        from drop_wd.forms import CEDropRequestForm

    if request.method == 'POST':

        form = CEDropRequestForm(data=request.POST)

        if form.is_valid():
            status = form.save(request)

            data = {
                'status':'success',
                'message':'Successfully submitted request(s)',
                'action': 'reload_table'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    ids = processable_ids(StudentRegistration, request.GET.getlist('ids[]'), request.user, campus_path='class_section__course__campus')
    form = CEDropRequestForm(ids)
    context = {
        'title': 'Create New Drop/WD Request(s)',
        'form': form
    }
    
    return render(request, template, context)

def send_to_sis(request):
    template = 'cis/students/send_to_sis.html'

    ids = processable_ids(StudentRegistration, request.GET.getlist('ids[]'), request.user, campus_path='class_section__course__campus')

    records = StudentRegistration.objects.filter(
        id__in=ids
    )

    import importlib.util
    if importlib.util.find_spec('ethos.ethos'):
        from ethos.ethos.library.ethos import Ethos
    else:
        from ethos.library.ethos import Ethos
    recLib = Ethos()

    summary = []
    for record in records:
        result, rez = get_tenant_service('registration').mirror_to_sis(record, request)
        summary += rez
        
    context = {
        'title': 'Send to SIS',
        'summary': summary
    }
    
    return render(request, template, context)

def manage_needs_mirroring(request):
    template = 'cis/registrations/set_needs_mirroring.html'

    from cis.forms.section import SetNeedsMirroringForm

    if request.method == 'POST':
        form = SetNeedsMirroringForm(data=request.POST)

        if form.is_valid():
            # Re-run campus authorization on the POST: the form's choices are
            # built from the submitted ids, so it validates any id. Only mutate
            # registrations this user is actually allowed to act on.
            allowed_ids = processable_ids(
                StudentRegistration, form.cleaned_data.get('registration_ids'),
                request.user, campus_path='class_section__course__campus')
            form.save(allowed_ids=allowed_ids)
            return JsonResponse({
                'status': 'success',
                'message': 'Successfully updated records',
                'action': 'reload_table'
            })

        return JsonResponse({
            'status': 'error',
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json()
        }, status=400)

    ids = processable_ids(
        StudentRegistration, request.GET.getlist('ids[]'), request.user,
        campus_path='class_section__course__campus')
    form = SetNeedsMirroringForm(ids)
    context = {
        'title': 'Set Needs Mirroring',
        'form': form
    }

    return render(request, template, context)


def manage_class_section_change(request):
    template = 'cis/registrations/change_section.html'

    from cis.forms.section import StudentClassChangeForm
    if request.method == 'POST':

        form = StudentClassChangeForm(data=request.POST)

        if form.is_valid():
            # Re-run campus authorization on POST: the form's choices are built
            # from the submitted ids, so it validates any id. Move only the
            # registrations this user is allowed to act on.
            allowed_ids = processable_ids(
                StudentRegistration, form.cleaned_data.get('registration_ids'),
                request.user, campus_path='class_section__course__campus')
            status = form.save(request=request, allowed_ids=allowed_ids)

            data = {
                'status':'success',
                'message':'Successfully updated records',
                'action': 'reload_table'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    ids = processable_ids(StudentRegistration, request.GET.getlist('ids[]'), request.user, campus_path='class_section__course__campus')
    form = StudentClassChangeForm(ids)
    context = {
        'title': 'Move to different Section',
        'form': form
    }
    
    return render(request, template, context)

def manage_registration_status(request):
    template = 'cis/registrations/update_status.html'

    if request.method == 'POST':
        form = StudentRegistrationChangeStatusForm(data=request.POST)

        if form.is_valid():
            # Re-run campus authorization on POST: the form's choices are built
            # from the submitted ids, so it validates any id. Mutate only the
            # registrations this user is allowed to act on.
            allowed_ids = processable_ids(
                StudentRegistration, form.cleaned_data.get('registration_ids'),
                request.user, campus_path='class_section__course__campus')
            status = form.save(allowed_ids=allowed_ids)

            data = {
                'status':'success',
                'message':'Successfully updated records',
                'action': 'reload_table'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    ids = processable_ids(StudentRegistration, request.GET.getlist('ids[]'), request.user, campus_path='class_section__course__campus')
    form = StudentRegistrationChangeStatusForm(ids)
    context = {
        'title': 'Change Registration Status',
        'form': form
    }
    
    return render(request, template, context)

class StudentRegistrationHistoryViewSet(viewsets.ViewSet):
    permission_classes = [CIS_user_only]

    def list(self, request):
        from ..serializers.history import HistorySerializer
        registration_id = request.GET.get('registration_id')
        try:
            StudentRegistration.objects.get(pk=registration_id)
        except StudentRegistration.DoesNotExist:
            return Response({'data': []})

        history = StudentRegistration.history.filter(id=registration_id).order_by('-history_date')
        serializer = HistorySerializer(history, many=True)
        return Response({'data': serializer.data})
