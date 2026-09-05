import csv
import io
import uuid

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cis.models.course import (
    Course, CourseAppRequirement,
    CourseAdministrator,
    CourseUpload
)
from ..models.note import CourseNote
from ..models.section import ClassSection
from myce.component_registry.course import course_tabs
from cis.services.table_configs import get_table_config

build_courses_table_config = get_table_config('courses_table').build_config
build_course_app_requirements_table_config = (
    get_table_config('course_app_requirements_table').build_config)

from cis.forms.course import (
    CourseForm, CourseAppRequirementForm,
    CourseAdministratorForm,
    CourseUploadForm,
    CourseStatusUpdateForm,
    MigrateForm,
    CourseCSVUploadForm,
    BulkAppRequirementUpdateForm,
    AddAppRequirementForm,
    BulkCourseAvailabilityForm,
    BulkCourseCampusForm,
    BulkCourseRegistrationEligibilityForm,
)

from django.template.loader import render_to_string

from cis.menu import cis_menu, draw_menu
from myce.component_registry.course import course_actions

from ..serializers.course import (
    CourseSerializer,
    CourseUploadSerializer,
    CourseAppRequirementSerializer,
)

from ..serializers.note import CourseNoteSerializer
from ..serializers.history import HistorySerializer
from cis.utils import CIS_user_only, INSTRUCTOR_user_only, FACULTY_user_only, user_has_cis_role, get_default_campus
from cis.campus_gate import scope_queryset_by_campus, campus_gate, get_accessible_campuses, processable_ids, can_process_campus

from cis.views.eager import (
    eager_queryset,
    with_course_note_related,
    with_course_related,
    with_course_upload_related,
)


@eager_queryset(with_course_upload_related)
class CourseAppRequirementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CourseAppRequirementSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        course_id = self.request.GET.get('course_id')
        records = CourseAppRequirement.objects.all()
        if course_id:
            records = CourseAppRequirement.objects.filter(course__id=course_id)
        return scope_queryset_by_campus(
            records, self.request.user, campus_path='course__campus')


class CourseHistoryViewSet(viewsets.ViewSet):
    permission_classes = [CIS_user_only]

    def list(self, request):
        course_id = request.GET.get('course_id')
        try:
            Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return Response({'data': []})

        history = Course.history.filter(id=course_id).order_by('-history_date')
        serializer = HistorySerializer(history, many=True)
        return Response({'data': serializer.data})


@eager_queryset(with_course_note_related)
class CourseNoteViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CourseNoteSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        course_id = self.request.GET.get('course_id')
        added_by = self.request.GET.get('added_by')

        if added_by:
            records = CourseNote.objects.filter(
                createdby__id=added_by
            )

            return records

        # get all notes for the student    
        try:
            return CourseNote.objects.filter(
                course__id=course_id)
        except:
            return CourseNote.objects.all()

@eager_queryset(with_course_upload_related)
class CourseUploadViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CourseUploadSerializer
    permission_classes = [CIS_user_only|INSTRUCTOR_user_only|FACULTY_user_only]

    def get_queryset(self):
        course_id = self.request.GET.get('course_id')

        if course_id:
            return CourseUpload.objects.filter(
                course__id=course_id
            )
        return CourseUpload.objects.all()

@eager_queryset(with_course_related)
class CourseViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CIS_user_only]
    serializer_class = CourseSerializer

    def get_queryset(self):
        
        cohorts = self.request.GET.get('cohort', None)
        campus = self.request.GET.get('campus', None)
        term = self.request.GET.get('term', None)
        faculty_coordinator_id = self.request.GET.get('faculty_coordinator_id')
        
        if term:
            course_ids = ClassSection.objects.filter(
                    term__id=term
                ).distinct('course').values_list('course__id', flat=True)
            records = Course.objects.filter(
                id__in=course_ids
            )
        else:
            records = Course.objects.all()

        if faculty_coordinator_id:

            # from cis.models.faculty import FacultyHighSchoolCoordinator

            # fac_courses = FacultyHighSchoolCoordinator.objects.filter(
            #     faculty_coordinator__id=faculty_coordinator_id
            # ).values_list('course', flat=True)

            fac_courses = CourseAdministrator.objects.filter(
                user__id=self.request.user.id,
                role__in=['Faculty', 'Dept. Chair'],
                status='Active'
            ).values_list('course', flat=True)

            records = records.filter(
                id__in=fac_courses
            )

        if cohorts and cohorts != 'undefined':
            cohorts = cohorts.split(',')
            records = records.filter(
                cohort__id__in=cohorts
            )

        if campus and campus != '-1':
            valid_campus = []
            for token in campus.split(','):
                try:
                    uuid.UUID(str(token))
                    valid_campus.append(token)
                except (ValueError, AttributeError, TypeError):
                    pass
            if valid_campus:
                records = records.filter(campus__id__in=valid_campus)

        records = scope_queryset_by_campus(records, self.request.user)
        records = records.order_by('cohort__designator', 'catalog_number')
        return records

def do_bulk_action(request):
    action = request.POST.get('action')

    if action == 'change_status':
        return manage_status(request)

    return course_actions.dispatch(request, action)


def manage_status(request):
    template = 'cis/highschools/update_status.html'

    if request.method == 'POST':

        record_id = request.POST.get('record_id')
        record = get_object_or_404(
            Course,
            pk=record_id
        )
        if not can_process_campus(request.user, record.campus):
            return JsonResponse({'status': 'error',
                'message': 'You are not authorized to access this campus.'}, status=403)

        form = CourseStatusUpdateForm(record=record, data=request.POST)
        if form.is_valid():
            status = form.save(request, record)

            data = {
                'status':'success',
                'message':'Successfully updated record',
                'action': 'reload_page'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    record_id = request.GET.get('record_id')
    record = get_object_or_404(
        Course,
        pk=record_id
    )
    if not can_process_campus(request.user, record.campus):
        return JsonResponse({'status': 'error',
            'message': 'You are not authorized to access this campus.'}, status=403)

    form = CourseStatusUpdateForm(record)
    context = {
        'title': 'Change Course Status',
        'form': form,
        'form_action': str(reverse('cis:course_bulk_actions'))
    }
    
    return render(request, template, context)


@course_actions.action('app_req', label='Update Status/Required', icon='fas fa-edit', scope=['bulk_app_req'])
def update_app_requirements(request):
    template = 'cis/course/bulk_action.html'
    ids_raw = request.POST.getlist('ids[]')
    ids = processable_ids(CourseAppRequirement, ids_raw, request.user, campus_path='course__campus')

    if request.POST.get('action_confirmed'):
        data = request.POST.copy()
        if ids_raw:
            data.setlist('record_ids', ids)
        else:
            data.setlist('record_ids', processable_ids(
                CourseAppRequirement, request.POST.getlist('record_ids'),
                request.user, campus_path='course__campus'))
        form = BulkAppRequirementUpdateForm(data=data)
        if form.is_valid():
            form.save(request)
            return JsonResponse({'outcome': 'call', 'fn': 'onBulkActionComplete', 'args': {'message': 'Successfully updated records', 'status': 'success'}})
        return JsonResponse({'message': 'Please correct the errors and try again.', 'errors': form.errors.as_json()}, status=400)

    form = BulkAppRequirementUpdateForm(ids)
    html = render_to_string(template, {
        'title': 'Update App Requirements',
        'form': form,
        'form_action': reverse('cis:course_bulk_actions'),
        'action_slug': 'update_app_requirements',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})


@course_actions.action('app_req', label='Add New', icon='fas fa-plus', btn_class='btn-success', scope=['add_new'])
def add_app_requirement(request):
    template = 'cis/course/bulk_action.html'

    if request.POST.get('action_confirmed'):
        data = request.POST.copy()
        gated_courses = processable_ids(Course, request.POST.getlist('courses'), request.user)
        data.setlist('courses', gated_courses)
        form = AddAppRequirementForm(data=data)
        if form.is_valid():
            created = form.save(request)
            return JsonResponse({'outcome': 'call', 'fn': 'onBulkActionComplete', 'args': {'message': f'Successfully created {len(created)} record(s)', 'status': 'success'}})
        return JsonResponse({'message': 'Please correct the errors and try again.', 'errors': form.errors.as_json()}, status=400)

    form = AddAppRequirementForm()
    html = render_to_string(template, {
        'title': 'Add App Requirement',
        'form': form,
        'form_action': reverse('cis:course_bulk_actions'),
        'action_slug': 'add_app_requirement',
        'ids': [],
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})


@course_actions.action('availability', label='Update Availability', icon='fas fa-edit', scope=['bulk'])
def update_course_availability(request):
    template = 'cis/course/bulk_action.html'
    ids = processable_ids(Course, request.POST.getlist('ids[]'), request.user)

    if request.POST.get('action_confirmed'):
        form = BulkCourseAvailabilityForm(data=request.POST)
        if form.is_valid():
            form.save(request)
            return JsonResponse({'outcome': 'call', 'fn': 'onBulkActionComplete', 'args': {'message': 'Successfully updated records', 'status': 'success'}})
        return JsonResponse({'message': 'Please correct the errors and try again.', 'errors': form.errors.as_json()}, status=400)

    form = BulkCourseAvailabilityForm(ids)
    html = render_to_string(template, {
        'title': 'Update Course Availability',
        'form': form,
        'form_action': reverse('cis:course_bulk_actions'),
        'action_slug': 'update_course_availability',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})


@course_actions.action('campus', label='Add/Update Campus', icon='fas fa-university', scope=['bulk'])
def update_course_campus(request):
    template = 'cis/course/bulk_action.html'
    ids_raw = request.POST.getlist('ids[]')
    ids = processable_ids(Course, ids_raw, request.user)

    if request.POST.get('action_confirmed'):
        data = request.POST.copy()
        if ids_raw:
            # ids[] was explicitly sent — inject campus-filtered result as record_ids
            data.setlist('record_ids', ids)
        else:
            # Confirm came with record_ids directly (modal flow or API); gate those too
            data.setlist('record_ids', processable_ids(
                Course, request.POST.getlist('record_ids'), request.user))
        form = BulkCourseCampusForm(data=data)
        if form.is_valid():
            form.save(request)
            return JsonResponse({'outcome': 'call', 'fn': 'onBulkActionComplete', 'args': {'message': 'Successfully updated records', 'status': 'success'}})
        return JsonResponse({'message': 'Please correct the errors and try again.', 'errors': form.errors.as_json()}, status=400)

    form = BulkCourseCampusForm(ids)
    html = render_to_string(template, {
        'title': 'Add/Update Campus',
        'form': form,
        'form_action': reverse('cis:course_bulk_actions'),
        'action_slug': 'update_course_campus',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})


@course_actions.action('eligibility', label='Update Registration Eligibility', icon='fas fa-user-check', scope=['bulk'])
def update_course_registration_eligibility(request):
    template = 'cis/course/bulk_action.html'
    ids_raw = request.POST.getlist('ids[]')
    ids = processable_ids(Course, ids_raw, request.user)

    if request.POST.get('action_confirmed'):
        # Campus-gate the confirm payload the same way update_course_campus
        # does. The ids the modal was built from are not the ids it posts back,
        # so re-filtering here is what stops a hand-crafted confirm from
        # rewriting eligibility on a course in another campus.
        data = request.POST.copy()
        if ids_raw:
            data.setlist('record_ids', ids)
        else:
            data.setlist('record_ids', processable_ids(
                Course, request.POST.getlist('record_ids'), request.user))
        form = BulkCourseRegistrationEligibilityForm(data=data)
        if form.is_valid():
            form.save(request)
            return JsonResponse({'outcome': 'call', 'fn': 'onBulkActionComplete', 'args': {'message': 'Successfully updated records', 'status': 'success'}})
        return JsonResponse({'message': 'Please correct the errors and try again.', 'errors': form.errors.as_json()}, status=400)

    form = BulkCourseRegistrationEligibilityForm(ids)
    html = render_to_string(template, {
        'title': 'Update Registration Eligibility',
        'form': form,
        'form_action': reverse('cis:course_bulk_actions'),
        'action_slug': 'update_course_registration_eligibility',
        'ids': ids,
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})


def delete_course_upload(request):
    upload_id = request.GET.get('upload_id')

    upload = get_object_or_404(
        CourseUpload,
        pk=upload_id
    )

    upload.delete()
    return JsonResponse(
        data = {
            'status':'success',
            'message':'Successfully deleted record',
            'action': 'reload'
        }
    )

def delete_course_administrator_role(request, record_id):
    record = get_object_or_404(CourseAdministrator, pk=record_id)

    try:        
        record.delete()

        data = {
            'status':'success',
            'message':'Successfully deleted record',
            'action': 'reload'
        }
    except Exception as e:
        data = {
            'status':'error',
            'message':'Unable to complete request.' + str(e),
        }
    return JsonResponse(data)

def manage_course_administrator_role(request):

    # PT-26: managing CourseAdministrator role assignments (create/update and
    # form prefill) is a CE-only action. add_new_ajax is shared across roles,
    # so the guard lives here in the handler.
    if not user_has_cis_role(request.user):
        return JsonResponse({
            'status': 'error',
            'message': 'You are not authorized to perform this action.',
        }, status=403)

    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/course/manage_administrator.html'

    course = None
    course_admin = None

    if request.method == 'POST':
        id = request.POST.get('id')
        
        course_admin = None
        if id != '-1':
            course_admin = get_object_or_404(
                CourseAdministrator, pk=id
            )

        form = CourseAdministratorForm(
                id=id,
                course=None,
                data=request.POST,
                instance=course_admin
            )
        
        if form.is_valid():
            course_admin = form.save(request, commit=True)

            data = {
                'status':'success',
                'message':'Successfully saved record',
                'new_record_id':course_admin.id,
                'new_record_name':course_admin.user.first_name,
                'action': 'reload'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again',
                'errors': form.errors
            }
            return JsonResponse(data)
    else:
        course_admin_id = request.GET.get('id')
        course_id = request.GET.get('parent')
        if course_id:
            course = get_object_or_404(Course, pk=course_id)

        if course_admin_id != '-1':
            course_admin = get_object_or_404(
                CourseAdministrator, pk=course_admin_id
            )
        form = CourseAdministratorForm(
            id=course_admin_id,
            course=course,
            instance=course_admin
        )
    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'record': course_admin,
            'base_template': base_template
        })

@campus_gate(Course, mode='json')
def delete(request, record_id):
    record = get_object_or_404(Course, pk=record_id)

    try:
        record.delete()
    
        data = {
            'status':'success',
            'message':'Success removed record',
        }   
    except Exception as e:
        data = {
            "status": 'warning',
            'message': e
        }

    return JsonResponse(data)


def change_si_availability(request):
    template = 'cis/course/update_si_availability.html'

    if request.method == 'POST':
        form = CourseSIAvailabilityChangeForm(data=request.POST)

        if form.is_valid():
            form.save(request)
            data = {
                'status': 'success',
                'message': 'Successfully updated records',
                'action': 'reload_table'
            }
            return JsonResponse(data)
        else:
            data = {
                'status': 'error',
                'message': 'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
            return JsonResponse(data, status=400)

    ids = processable_ids(Course, request.GET.getlist('ids[]'), request.user)
    form = CourseSIAvailabilityChangeForm(ids)
    context = {
        'title': 'Change SI Availability',
        'form': form,
    }
    return render(request, template, context)


def tab(request, record_id, tab_slug):
    """Render a single Course detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(Course, pk=record_id)
    return course_tabs.render_tab(request, record, tab_slug)


@xframe_options_exempt
@campus_gate(Course, mode='page')
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/course/course.html'
    record = get_object_or_404(Course, pk=record_id)
 
    course_app_id = request.GET.get('course_app_id')
    course_app_req = None

    course_admin_id = request.GET.get('course_admin_id')
    course_admin = None

    form = CourseForm(instance=record)
    file_form = CourseUploadForm(course=record, user=request.user)

    if course_app_id:
        course_app_req = get_object_or_404(
            CourseAppRequirement, pk=course_app_id
        )        
    course_app_req_form = CourseAppRequirementForm(
        instance=course_app_req
    )

    migration_form = MigrateForm(record=record)
    if request.method == 'POST':
        
        if request.POST.get('action') == 'migrate_course':
            migration_form = MigrateForm(
                record=record, data=request.POST
            )

            if migration_form.is_valid():
                success, message = migration_form.save(request, record)

                if not success:
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Your request was processed with some errors.<br>' + '<br>'.join(message),
                        'list-group-item-warning')
                else:
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Successfully completed request. ' + ','.join(message),
                        'list-group-item-success')
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Please correct the errors and try again',
                    'list-group-item-danger')
                
        elif request.POST.get('action') == 'upload_file':
            file_form = CourseUploadForm(
                record,
                request.user,
                request.POST,
                request.FILES
            )

            if file_form.is_valid():
                upload = file_form.save()
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully saved file',
                    'list-group-item-success') 
                return redirect('cis:course', record_id=record_id)

        elif request.POST.get('action') == 'save_course':
            form = CourseForm(request.POST, instance=record)

            if form.is_valid():
                record = form.save(commit=False)
                if not record.meta:
                    record.meta = {}

                record.meta['available_for_si'] = form.cleaned_data.get('available_for_si')
                record.meta['available_for_new_schools'] = form.cleaned_data.get('available_for_new_schools')

                record.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:course', record_id=record_id)
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Please fix the error(s) and try again ' + str(form.errors),
                    'list-group-item-danger')

        if request.POST.get('action') == 'save_course_app_req':
            course_app_req_form = CourseAppRequirementForm(
                request.POST,
                instance=course_app_req
            )
            if course_app_req_form.is_valid():
                course_app_req = course_app_req_form.save(commit=False)
                course_app_req.course = record
                course_app_req.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully saved record',
                    'list-group-item-success')
                return redirect('cis:course', record_id=record_id)

        if request.POST.get('action') == 'save_course_admin':
            course_admin_form = CourseAdministratorForm(
                course=record,
                data=request.POST,
                instance=course_admin
            )
            if course_admin_form.is_valid():
                course_admin = course_admin_form.save(request, commit=True)

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully saved record',
                    'list-group-item-success')
                return redirect('cis:course', record_id=record_id)

    from myce.component_registry.course import course_actions

    return render(
        request,
        template, {
            'page_title': "Course Details",
            'labels': {
                'all_items': 'All Courses'
            },
            'urls': {
                'add_new': 'cis:course_add_new',
                'all_items': 'cis:courses'
            },
            'menu': draw_menu(cis_menu, 'classes', 'courses'),
            'record': record,
            'detail_actions': course_actions.for_scope('detail', request.user),
            'detail_tabs': course_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse('cis:course_tab', args=[record.id, slug]),
            ),
        })

def import_courses_from_file(request):
    """Handle CSV file upload for Course import."""
    from cis.services.importers import CourseRow

    form = CourseCSVUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded_file))

        result = Course.import_from_csv(reader)
        if result['status'] == 'success':
            if not result['records']:
                messages.add_message(
                    request,
                    messages.WARNING,
                    'The uploaded file contained no data rows.',
                    'list-group-item-warning')
                return redirect('cis:course_add_new')

            file_name = "course_import_results.csv"
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{file_name}"'

            writer = csv.writer(response)
            writer.writerow(result['records'][0].keys())
            for row in result['records']:
                writer.writerow(row.values())
            return response

        messages.add_message(
            request,
            messages.SUCCESS,
            'There was an error processing the file.' + result.get('message', ''),
            'list-group-item-danger')
        return redirect('cis:course_add_new')


def download_course_template(request):
    """Download a blank CSV template with the correct headers for Course import."""
    from cis.services.importers import CourseRow

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="course_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(CourseRow.csv_headers())
    return response


def add_new(request):
    '''
    Add new page
    '''
    from cis.services.importers import CourseRow

    base_template = 'cis/logged-base.html'
    template = 'cis/course/course-add_new.html'
    ajax = request.GET.get('ajax', None)
    upload_form = CourseCSVUploadForm()

    if request.method == 'POST':
        if request.POST.get('upload_file') == "Import Courses":
            return import_courses_from_file(request)

        form = CourseForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            record = form.save(commit=False)

            if not record.meta:
                record.meta = {}

            record.meta['available_for_si'] = form.cleaned_data.get('available_for_si')
            record.meta['available_for_new_schools'] = form.cleaned_data.get('available_for_new_schools')

            record.save()

            if ajax == '1':
                data = {
                    'status':'success',
                    'message':'Successfully added new record',
                    'new_record_id':record.id,
                    'new_record_name':record.name
                }
                return JsonResponse(data)

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully added record',
                'list-group-item-success')
            return redirect('cis:courses')

        else:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Please fix the error(s) and try again. ' + str(form.errors),
                'list-group-item-danger'
            )
    else:
        form = CourseForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    context = {
        'form': form,
        'page_title': "Add New",
        'labels': {
            'all_items': 'All Courses'
        },
        'urls': {
            'add_new': 'cis:course_add_new',
            'all_items': 'cis:courses'
        },
        'ajax': ajax,
        'base_template': base_template,
        'menu': draw_menu(cis_menu, 'classes', 'courses')
    }

    if not ajax:
        context['upload_form'] = upload_form
        context['schema_fields'] = CourseRow.field_definitions()
        context['required_header'] = CourseRow.csv_headers()

    return render(request, template, context)

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'classes', 'courses')
    template = 'cis/course/courses.html'
    
    return render(
        request,
        template, {
            'page_title': 'Courses',
            'urls': {
                'add_new': 'cis:course_add_new',
                'details_prefix': '/ce/course/'
            },
            'menu': menu,
            'accessible_campuses': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            # Kept for the instructor_app course_requirements include:
            'course_administrator_url': '/ce/api/course_administrator?format=datatables',
            'course_requirements_url': '/ce/instructor_apps/api/course-requirements?format=datatables',
            'course_req_bulk_actions_url': '/ce/instructor_apps/courses/req_bulk_actions',
            # Table configs (replace the old inline tables + init script):
            'courses_table': build_courses_table_config(
                variant='courses_index',
                api_url='/ce/api/course?format=datatables',
                details_prefix='/ce/course/',
                bulk_actions=course_actions.for_scope('bulk', request.user),
                bulk_actions_url=reverse('cis:course_bulk_actions'),
                filter_form_selector='#courses_campus_filter',
            ),
            'course_app_requirements_table': build_course_app_requirements_table_config(
                variant='course_app_requirements_index',
                api_url='/ce/api/course-app-requirement?format=datatables',
                details_prefix='/ce/course/',
                bulk_actions=course_actions.for_scope('bulk_app_req', request.user),
                bulk_actions_url=reverse('cis:course_bulk_actions'),
                add_actions=course_actions.for_scope('add_new', request.user),
            ),
        }
    )
