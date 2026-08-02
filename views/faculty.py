import io
import csv

from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.conf import settings

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse, JsonResponse
from django.urls import reverse

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cis.serializers.faculty import FacultySerializer, CourseAdministratorSerializer

from cis.models.course import (
    Course,
    CourseAdministrator
)
from cis.models.customuser import CustomUser
from cis.models.faculty import (
    FacultyCoordinator, FacultyCourseCoordinator
)
from cis.forms.faculty import (
    FacultyCoordinatorForm,
    FacultyCSVUploadForm,
    FacultyCourseAdministratorForm,
    FacultyCourseChangeStatusForm,
    FacultyCooridnatorStatusUpdateForm
)
from cis.services.importers import FacultyRow
from cis.utils import (
    CIS_user_only,
    FACULTY_user_only
)
from cis.campus_gate import scope_queryset_by_campus, processable_ids, can_process_campus
from cis.models.note import TeacherNote

from cis.forms.teacher import (
    TeacherForm, TeacherHighSchoolForm,
    TeacherCourseForm
)

from cis.menu import cis_menu, draw_menu

from myce.component_registry.faculty_coordinator import faculty_coordinator_tabs


class CourseAdministratorViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CourseAdministratorSerializer
    permission_classes = [CIS_user_only|FACULTY_user_only]

    def get_queryset(self):
        course_id = self.request.GET.get('course_id')
        status = self.request.GET.get('status', 'active')
        faculty_coordinator_user_id = self.request.GET.get('faculty_coordinator_user_id')
        campus = self.request.GET.get('campus', '').strip()

        if course_id:
            records = CourseAdministrator.objects.filter(
                course__id=course_id, status__iexact='active')
        elif faculty_coordinator_user_id:
            records = CourseAdministrator.objects.filter(
                user__id=faculty_coordinator_user_id)
        else:
            records = CourseAdministrator.objects.all()

        # Gate by the administered course's campus (ce users only), then narrow
        # to the dropdown's chosen campus if one is selected — like /ce/courses.
        records = scope_queryset_by_campus(
            records, self.request.user, campus_path='course__campus')
        if campus:
            records = records.filter(course__campus__id=campus)
        return records

class FacultyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FacultySerializer
    permission_classes = [CIS_user_only|FACULTY_user_only]

    def get_queryset(self):
        # One row per person. Deliberately not campus-gated: FacultyCoordinator
        # has no campus, and gating through course assignments would hide
        # faculty who administer no courses. Ordered so server-side pagination
        # is stable across pages.
        return FacultyCoordinator.objects.select_related(
            'user', 'department',
        ).order_by('user__last_name', 'user__first_name')

def index(request):
    '''
    Teacher search and index page for staff
    '''
    from cis.services.table_configs import get_table_config
    build_faculty_coords_table_config = get_table_config('faculty_coords_table').build_config
    build_faculty_table_config = get_table_config('faculty_table').build_config

    from cis.campus_gate import get_accessible_campuses
    from cis.utils import get_default_campus

    menu = draw_menu(cis_menu, 'fac_coords', 'fac_coords')
    template = 'cis/faculty/index.html'


    return render(
        request,
        template, {
            'page_title': 'Faculty',
            'urls': {
            },
            'menu': menu,
            'api_url': '/ce/api/faculty?format=datatables',
            'course_administrator_url': '/ce/api/course_administrator?format=datatables',
            'accessible_campuses': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'faculty_table': build_faculty_table_config(
                variant='faculty_index',
                api_url='/ce/api/faculty?format=datatables',
                details_prefix='/ce/faculty_coordinator/',
            ),
            'faculty_coords_table': build_faculty_coords_table_config(
                variant='faculty_coords_index',
                api_url='/ce/api/course_administrator?format=datatables',
                details_prefix='/ce/faculty_coordinator/',
                bulk_actions={
                    'change_course_administrator_status': {
                        'label': 'Change Status',
                        'icon': 'fas fa-edit',
                        'btn_class': 'btn-primary',
                        'confirm': None,
                    },
                },
                filter_form_selector='#faculty_filter',
            ),
        }
    )


def import_faculty_from_file(request):
    """Handle CSV upload for faculty import; returns a results CSV."""
    upload_form = FacultyCSVUploadForm(request.POST, request.FILES)
    if not upload_form.is_valid():
        messages.add_message(request, messages.ERROR,
                             'Please choose a CSV file to upload.', 'list-group-item-danger')
        return redirect('cis:faculty_coordinator_add_new')

    uploaded = request.FILES.get('file')
    try:
        decoded = uploaded.read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded))
    except Exception:
        messages.add_message(request, messages.ERROR,
                             'Could not read the uploaded file.', 'list-group-item-danger')
        return redirect('cis:faculty_coordinator_add_new')

    result = FacultyCoordinator.import_from_csv(reader)
    records = result.get('records', [])
    if not records:
        messages.add_message(request, messages.ERROR,
                             'The file had no data rows.', 'list-group-item-danger')
        return redirect('cis:faculty_coordinator_add_new')

    # stream a results CSV: original columns + RESULT
    fieldnames = list(records[0].keys())
    if 'RESULT' not in fieldnames:
        fieldnames.append('RESULT')
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    for r in records:
        writer.writerow(r)
    response = HttpResponse(out.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="faculty_import_results.csv"'
    return response


def download_faculty_template(request):
    """Download a blank CSV template with the correct faculty headers."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="faculty_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(FacultyRow.csv_headers())
    return response


def add_new(request):
    '''
    Add new page
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/faculty/add_new.html'

    if request.method == 'POST':
        if request.POST.get('upload_file') == 'Import Faculty':
            return import_faculty_from_file(request)

        form = FacultyCoordinatorForm(None, request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            try:
                user = CustomUser()
                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.email = form.cleaned_data['email'].lower()
                user.username = form.cleaned_data['email'].lower()
                user.primary_phone = form.cleaned_data['primary_phone']
                user.psid = form.cleaned_data['psid']

                user.address1 = form.cleaned_data['address1']
                user.city = form.cleaned_data['city']
                user.state = form.cleaned_data['state']
                user.postal_code = form.cleaned_data['postal_code']

                #check if user email is already in the system
                if not CustomUser.objects.filter(
                    email=form.cleaned_data['email']).exists():
                    user.save()
                else:
                    user = CustomUser.objects.get(email=form.cleaned_data['email'])

                record = FacultyCoordinator(user=user)
                # record.department = form.cleaned_data['department']
                # record.fac_assistant = form.cleaned_data['fac_assistant']
                record.save()

                for course in form.cleaned_data.get('courses'):
                    course_admin = CourseAdministrator(
                        course=course,
                        role=form.cleaned_data.get('course_admin_role'),
                        status='Active',
                        user=user
                    )
                    course_admin.save()

                if ajax == '1':
                    data = {
                        'status':'success',
                        'message':'Successfully added new record',
                        'new_record_id':record.id,
                        'new_record_name':record.user.first_name
                    }
                    return JsonResponse(data)

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully added record',
                    'list-group-item-success')
                return redirect('cis:faculty_coordinators') #d
            except IntegrityError as intError:
                form._errors['email'] = ['Sorry, a faculty coordinator account with this email already exists']

        else:
            print(form.errors)
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = FacultyCoordinatorForm()

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax, 
            'page_title': "Add New",
            'labels': {
                'all_items': 'All'
            },
            'urls': {
                'add_new': 'cis:faculty_coordinator_add_new',
                'all_items': 'cis:faculty_coordinators'
            },
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'fac_coords', 'fac_coord'),
            'upload_form': FacultyCSVUploadForm(),
            'schema_fields': FacultyRow.field_definitions(),
        })

from django.views.decorators.clickjacking import xframe_options_exempt


def tab(request, record_id, tab_slug):
    """Render a single FacultyCoordinator detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(FacultyCoordinator, pk=record_id)
    return faculty_coordinator_tabs.render_tab(request, record, tab_slug)


@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/faculty/detail.html'
    record = get_object_or_404(FacultyCoordinator, pk=record_id)

    if request.method == 'POST':
        form = FacultyCoordinatorForm(record, request.POST)

        if form.is_valid():
            try:
                record = form.save(record)

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:faculty_coordinator', record_id=record_id)
            except IntegrityError:
                form._errors['email'] = ['An account with this email/username already exists.']
    else:
        form = FacultyCoordinatorForm(record)

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Faculty Details",
            'labels': {
                'all_items': 'All'
            },
            'urls': {
                'add_new': 'cis:faculty_coordinator_add_new',
                'all_items': 'cis:faculty_coordinators'
            },
            'menu': draw_menu(cis_menu, 'fac_coords', 'fac_coord'),
            'record': record,
            'detail_tabs': faculty_coordinator_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse(
                    'cis:faculty_coordinator_tab', args=[record.id, slug]),
            ),
        })

def do_bulk_action(request):
    action = request.GET.get('action')

    if request.method == 'POST':
        action = request.POST.get('action')
        
    if action == 'change_status':
        return manage_status(request)

    if action == 'change_course_administrator_status':
        return manage_course_administrator_status(request)

    data = {
        'status': 'success',
        'message': 'invalid action passed'
    }
    return JsonResponse(data)

def manage_status(request):
    template = 'cis/faculty/update_course_administrator_status.html'

    if request.method == 'POST':

        record_id = request.POST.get('record_id')
        record = get_object_or_404(
            FacultyCoordinator,
            pk=record_id
        )

        form = FacultyCooridnatorStatusUpdateForm(record=record, data=request.POST)
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
        FacultyCoordinator,
        pk=record_id
    )

    form = FacultyCooridnatorStatusUpdateForm(record)
    context = {
        'title': 'Change Status',
        'form': form,
        'form_action': str(reverse('cis:faculty_bulk_actions'))
    }
    
    return render(request, template, context)

def manage_course_administrator_status(request):
    template = 'cis/faculty/update_course_administrator_status.html'

    if request.method == 'POST':
        post_data = request.POST.copy()
        post_data.setlist(
            'faculty_course_administrator_ids',
            processable_ids(
                CourseAdministrator,
                request.POST.getlist('faculty_course_administrator_ids'),
                request.user,
                campus_path='course__campus',
            ),
        )
        form = FacultyCourseChangeStatusForm(data=post_data)

        if form.is_valid():
            status = form.save()

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

    ids_raw = request.GET.getlist('ids[]')
    ids = processable_ids(CourseAdministrator, ids_raw, request.user, campus_path='course__campus')
    form = FacultyCourseChangeStatusForm(ids)
    context = {
        'title': 'Change Status',
        'form': form,
        'form_action': str(reverse('cis:faculty_bulk_actions'))
    }

    return render(request, template, context)

def add_new_course(request):
    '''
    Add new course to faculty coordinator
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/faculty/manage_course.html'

    faculty = None
    course_admin = None

    if request.method == 'POST':
        id = request.POST.get('id')
        
        course_admin = None
        if id != '-1':
            course_admin = get_object_or_404(
                CourseAdministrator, pk=id
            )

        form = FacultyCourseAdministratorForm(
                id=id,
                faculty=faculty,
                data=request.POST,
                instance=course_admin
            )
        
        if form.is_valid():
            course_admin = form.save(request, course_admin, commit=True)

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
        faculty_id = request.GET.get('parent')
        if faculty_id:
            faculty = get_object_or_404(FacultyCoordinator, pk=faculty_id)

        if course_admin_id != '-1':
            course_admin = get_object_or_404(
                CourseAdministrator, pk=course_admin_id
            )
        form = FacultyCourseAdministratorForm(
            id=course_admin_id,
            faculty=faculty,
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
