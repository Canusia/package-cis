import logging

from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.conf import settings

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
import csv
import io
from django.http import JsonResponse, FileResponse, Http404, HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

import os

from rest_framework import viewsets

from rest_framework.decorators import api_view, action
from rest_framework.response import Response

from cis.models.course import Course
from cis.campus_gate import scope_by_course_cert_campus
from cis.models.customuser import CustomUser
from cis.models.teacher import (
    Teacher, TeacherHighSchool, TeacherCourseCertificate,
    TeacherUpload
)
import importlib.util
import uuid
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.models import FutureCourse, FutureSection
else:
    from future_sections.models import FutureCourse, FutureSection
from cis.models.section import ClassSection, SectionNumber
from cis.models.note import TeacherNote

from cis.forms.teacher import (
    TeacherForm, TeacherHighSchoolForm,
    TeacherCourseForm,
    TeacherUploadForm,
    EdBgForm,
    TeacherStatusUpdateForm,
    MigrateForm,
    InstructorCSVUploadForm,
)

from ..serializers.teacher import (
    TeacherSerializer, TeacherUploadSerializer, TeacherUploadListSerializer,
    DanglingInstructorSerializer
)
from ..serializers.highschool import HighSchoolTeacherSerializer, TeacherCourseSerializer
from ..serializers.note import TeacherNoteSerializer
from cis.services.table_configs import get_table_config
build_sections_table_config = get_table_config('sections_table').build_config
build_instructors_table_config = get_table_config('instructors_table').build_config
build_instructor_dangling_table_config = get_table_config('instructor_dangling_table').build_config

from myce.component_registry.teacher import teacher_tabs

from cis.utils import (
    CIS_user_only, INSTRUCTOR_user_only, FACULTY_user_only, HSADMIN_user_only,
    user_has_cis_role, user_has_instructor_role, user_has_highschool_admin_role,
    user_has_faculty_role,
)
from cis.menu import cis_menu, draw_menu
from cis.services.faculty_scope import visible_teachers

from cis.views.eager import (
    eager_queryset,
    with_teacher_course_related,
    with_teacher_note_related,
    with_teacher_related,
)

from cis.serializers import tables

logger = logging.getLogger(__name__)

@eager_queryset(with_teacher_course_related)
class TeacherCourseViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TeacherCourseSerializer
    permission_classes = [CIS_user_only]

    def get_serializer_class(self):
        # Narrow serializer for the datatables feed only; format=json callers
        # and the retrieve action keep the full one (#67).
        return tables.datatables_serializer(
            self, tables.SlimTeacherCourseSerializer)

    def get_queryset(self):
        teacher_id = self.request.GET.get('teacher_id')
        course_id = self.request.GET.get('course_id')
        cohort_id = self.request.GET.get('cohort_id')

        records = TeacherCourseCertificate.objects.all()
        if teacher_id:
            records = records.filter(
                teacher_highschool__teacher__id=teacher_id
            )
        if course_id:
            records = records.filter(course__id=course_id)
        if cohort_id:
            records = records.filter(course__cohort__id=cohort_id)
        return records

class TeacherUploadViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TeacherUploadSerializer
    permission_classes = [
        CIS_user_only | INSTRUCTOR_user_only | HSADMIN_user_only
    ]

    def get_queryset(self):
        """Scope teacher uploads to the caller's role (PT-11).

        Role precedence (most privileged first):
          * ce               -> full access; may target any teacher_id or list all.
          * highschool_admin  -> only uploads for teachers in their high schools.
          * instructor        -> only their own uploads; client teacher_id ignored.
        Any other authenticated user gets an empty queryset. The scoped
        queryset is also the object-level check: retrieve() filters through
        get_queryset(), so out-of-scope detail lookups return 404.
        """
        user = self.request.user
        teacher_id = self.request.GET.get('teacher_id')

        # Guard a client-supplied teacher_id: a non-UUID value (e.g. an
        # uninitialised "PLACEHOLDER" from the UI, or fuzzing) would raise
        # ValidationError -> 500 in the teacher__id filter below. Treat a
        # present-but-malformed teacher_id as "no match" (empty) in the
        # branches that filter by it. (Same idiom as the PT-1 term_id guard.)
        teacher_id_is_valid_uuid = False
        if teacher_id:
            try:
                uuid.UUID(str(teacher_id))
                teacher_id_is_valid_uuid = True
            except (ValueError, AttributeError, TypeError):
                teacher_id_is_valid_uuid = False

        # CE administrators: arbitrary teacher_id and global listing allowed.
        if user_has_cis_role(user):
            records = TeacherUpload.objects.all()
            if teacher_id:
                if not teacher_id_is_valid_uuid:
                    return TeacherUpload.objects.none()
                records = records.filter(teacher__id=teacher_id)
            return records

        # Highschool admins: only teachers tied to a high school they manage.
        if user_has_highschool_admin_role(user):
            highschool_ids = user.get_highschools_for_admin()
            teacher_ids = TeacherHighSchool.objects.filter(
                highschool__id__in=highschool_ids
            ).values_list('teacher_id', flat=True)
            records = TeacherUpload.objects.filter(teacher__id__in=teacher_ids)
            if teacher_id:
                if not teacher_id_is_valid_uuid:
                    return TeacherUpload.objects.none()
                records = records.filter(teacher__id=teacher_id)
            return records

        # Instructors: only their own uploads; never trust client teacher_id.
        if user_has_instructor_role(user):
            return TeacherUpload.objects.filter(teacher__user=user)

        # Faculty: only uploads for instructors in their visible set (spec
        # 2026-08-11, faculty -> teacher assignment). permission_classes above
        # admit ce/instructor/highschool_admin only, so a faculty-only user is
        # still 403 here -- deliberately not widened by this change. The branch
        # exists so the scope, not an accident of the permission list, is what
        # protects the data if the faculty portal is ever granted the endpoint.
        if user_has_faculty_role(user):
            records = TeacherUpload.objects.filter(
                teacher__in=visible_teachers(user))
            if teacher_id:
                if not teacher_id_is_valid_uuid:
                    return TeacherUpload.objects.none()
                records = records.filter(teacher__id=teacher_id)
            return records

        return TeacherUpload.objects.none()

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        """Stream an upload's file behind the same role scope as the list (PT-11).

        Resolving the object through get_object() (which filters through
        get_queryset()) means an out-of-scope upload yields 404 -- a caller can
        never download another instructor's file even with its UUID. The file is
        streamed from private storage so no pre-signed S3 URL is ever exposed;
        the response is marked no-store so intermediaries don't cache it.
        """
        upload = self.get_object()  # 404 if outside the caller's role scope

        if not upload.media:
            raise Http404('No file associated with this upload.')

        filename = os.path.basename(upload.media.name) or 'download'

        response = FileResponse(
            upload.media.open('rb'),
            as_attachment=True,
            filename=filename,
        )
        response['Cache-Control'] = 'no-store'
        return response

class AllTeacherUploadViewSet(TeacherUploadViewSet):
    """Every instructor upload, flattened, for the CE Instructors > Files tab.

    Subclasses TeacherUploadViewSet rather than restating a CIS-only queryset so
    the PT-11 role scoping and the authorized `download` action are inherited,
    not duplicated. A separate copy of the scoping logic would drift from the
    original the first time either is touched. Inheriting it also means a
    highschool_admin reaching this endpoint gets their own scoped view of the
    same table for free, instead of a blanket 403.

    Only the presentation differs: a flat serializer (no nested TeacherSerializer
    per row) plus an optional media_type filter and a default ordering by
    instructor name.
    """
    serializer_class = TeacherUploadListSerializer

    def get_queryset(self):
        records = super().get_queryset().select_related('teacher', 'teacher__user')

        media_type = self.request.GET.get('media_type')
        if media_type:
            records = records.filter(media_type=media_type)

        return records.order_by(
            'teacher__user__last_name', 'teacher__user__first_name', '-uploaded_on')

@eager_queryset(with_teacher_related)
class TeacherViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TeacherSerializer
    permission_classes = [
        CIS_user_only | FACULTY_user_only | INSTRUCTOR_user_only | HSADMIN_user_only
    ]

    def get_queryset(self):

        status = self.request.GET.get('status')
        record_type = self.request.GET.get('record_type')
        faculty_coordinator_id = self.request.GET.get('faculty_coordinator_id')
        teacher_id = self.request.GET.get('teacher_id')
        
        records = Teacher.objects.all()


        if teacher_id:
            teacher_courses = TeacherCourseCertificate.objects.filter(
                teacher_highschool__teacher__id=teacher_id
            )

            teacher_courses = TeacherCourseCertificate.objects.filter(
                course__id__in=teacher_courses.values_list('course__id', flat=True)
            )

            records = records.filter(
                id__in=teacher_courses.values_list(
                    'teacher_highschool__teacher__id', flat=True
                )
            )

        if faculty_coordinator_id:
            from cis.models.course import CourseAdministrator
            fac_courses = CourseAdministrator.objects.filter(
                user=faculty_coordinator_id,
                status__iexact='active'
            )

            course_teachers = TeacherCourseCertificate.objects.filter(
                course__id__in=fac_courses.values_list('course__id', flat=True)
            )

            records = records.filter(
                id__in=course_teachers.values_list(
                    'teacher_highschool__teacher__id',
                    flat=True
                )
            )

        if record_type:
            # if record_type == 'active_inactive':
            #     records = records.filter(
            #         status__in=['active', 'inactive']
            #     )
            
            if record_type == 'active':
                records = records.filter(
                    status__in=['active']
                )

        if status:
            records = records.filter(status__iexact=status)

        # PT-11: scope teacher records to the caller's role (applied last,
        # after all other filters). Mirrors the TeacherUploadViewSet fix.
        #   * ce                -> all teachers (CE index), campus-gated.
        #   * faculty           -> only the instructors they may see, per
        #                          cis/services/faculty_scope.visible_teachers.
        #   * highschool_admin  -> teachers in the high schools they manage.
        #   * instructor        -> only their own Teacher record.
        # ce is checked first because user_has_faculty_role() is also True for
        # ce users. retrieve() runs through this queryset, so an out-of-scope
        # teacher UUID returns 404.
        user = self.request.user
        if user_has_cis_role(user):
            # Campus gate (ce only): scope to instructors certified for courses
            # at a processable campus; instructors with no course certs are
            # universal. The dropdown narrows to the chosen campus.
            campus = self.request.GET.get('campus', '').strip()
            return scope_by_course_cert_campus(
                records, user,
                cert_path='teacherhighschool__teachercoursecertificate',
                selected_campus=campus or None)

        if user_has_faculty_role(user):
            # Faculty -> teacher assignment (spec 2026-08-11): per overseen
            # course, the assigned instructors when CE has configured any for
            # this academic year, otherwise the full certificate list that has
            # always been shown. Ships dark: with no assignment rows this is
            # exactly today's derivation.
            #
            # This is an additional AND on top of every filter above --
            # including the client-supplied faculty_coordinator_id, which
            # narrows by *that* faculty's courses. Replacing rather than
            # intersecting would let a faculty user pass a colleague's id and
            # widen their own view.
            #
            # No campus gate: scope_by_course_cert_campus() is a no-op for
            # non-ce, non-superuser callers.
            return records.filter(
                id__in=visible_teachers(user).values('id'))

        if user_has_highschool_admin_role(user):
            highschool_ids = user.get_highschools_for_admin()
            teacher_ids = TeacherHighSchool.objects.filter(
                highschool__id__in=highschool_ids
            ).values_list('teacher_id', flat=True)
            return records.filter(id__in=teacher_ids)

        if user_has_instructor_role(user):
            return records.filter(user=user)

        return records.none()

class DanglingInstructorViewSet(viewsets.ReadOnlyModelViewSet):
    """Accounts left in the instructor group with no Teacher record.

    They appear on no other tab: the instructor tabs are driven by Teacher
    records, which these users no longer have. This is the only place staff
    can reach them.
    """
    serializer_class = DanglingInstructorSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        from cis.services.role_access import dangling_users
        from cis.services.instructor_role import INSTRUCTOR

        return dangling_users(INSTRUCTOR)

@eager_queryset(with_teacher_note_related)
class TeacherNotesViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TeacherNoteSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        teacher_id = self.request.GET.get('teacher_id')

        records = TeacherNote.objects.all()

        # Faculty: only notes about instructors in their visible set (spec
        # 2026-08-11). Same reachability caveat as TeacherUploadViewSet --
        # permission_classes is CIS_user_only, so a faculty-only user is 403
        # today and this change does not widen that; it makes the scope, rather
        # than the permission list alone, what protects the data.
        # user_has_faculty_role() is True for ce users, so ce is excluded first.
        user = self.request.user
        if not user_has_cis_role(user) and user_has_faculty_role(user):
            records = records.filter(teacher__in=visible_teachers(user))

        if teacher_id:
            records = records.filter(
                teacher__id=teacher_id
            )
        return records

def do_bulk_action(request):
    action = request.GET.get('action')

    if request.method == 'POST':
        action = request.POST.get('action')
        
    if action == 'change_status':
        return manage_status(request)

    if action == 'change_password':
        return manage_change_password(request)
    
    if action == 'change_password_by_hs':
        return manage_change_password_by_hs(request)
    
    data = {
        'status': 'success',
        'message': 'invalid action passed'
    }
    return JsonResponse(data)

def manage_change_password(request):
    template = 'cis/teachers/change_password.html'

    from cis.forms.teacher import BulkPasswordChangeForm
    if request.method == 'POST':

        form = BulkPasswordChangeForm(data=request.POST)

        if form.is_valid():
            status = form.save(request)

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

    ids = request.GET.getlist('ids[]')

    form = BulkPasswordChangeForm(ids)
    context = {
        'title': 'Change Password',
        'form': form,
        'id': 'frm_bulk_password',
        'form_action': str(reverse('cis:teacher_bulk_actions')),
        'status': 'display'
    }
    
    return render(request, template, context)

def manage_change_password_by_hs(request):
    template = 'cis/teachers/change_password.html'

    from cis.forms.teacher import BulkPasswordChangeForm
    ids = request.GET.getlist('ids[]')

    teacher_hs = TeacherHighSchool.objects.filter(id__in=ids)
    ids = teacher_hs.values_list('teacher__id', flat=True)

    form = BulkPasswordChangeForm(ids)
    context = {
        'title': 'Change Password',
        'form': form,
        'id': 'frm_bulk_password',
        'form_action': str(reverse('cis:teacher_bulk_actions')),
        'status': 'display'
    }
    
    return render(request, template, context)

def manage_status(request):
    template = 'cis/teachers/bulk_action.html'

    if request.method == 'POST':

        record_id = request.POST.get('record_id')
        record = get_object_or_404(
            Teacher,
            pk=record_id
        )

        form = TeacherStatusUpdateForm(record=record, data=request.POST)
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
        Teacher,
        pk=record_id
    )

    form = TeacherStatusUpdateForm(record)
    context = {
        'title': 'Change Status',
        'form': form,
        'form_action': str(reverse('cis:teacher_bulk_actions'))
    }
    
    return render(request, template, context)

def index(request):
    '''
    Teacher search and index page for staff
    '''
    from cis.campus_gate import get_accessible_campuses
    from cis.utils import get_default_campus

    menu = draw_menu(cis_menu, 'instructors', 'instructors')
    template = 'cis/teachers/teachers.html'

    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'Instructors',
            'api_url': '/ce/api/teacher?format=datatables',
            'teacher_hs_api_url': '/ce/api/highschool-teacher?format=datatables',
            'teacher_uploads_api_url': '/ce/api/all-teacher-uploads?format=datatables',
            'accessible_campuses': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'urls': {
                'details_prefix': '/ce/instructor/',
                'add_new': 'cis:instructor_add_new'
            },
            'instructors_table': build_instructors_table_config(
                variant='instructors_index',
                api_url='/ce/api/teacher?format=datatables',
                details_prefix='/ce/instructor/',
                bulk_actions={
                    'change_password': {
                        'label': 'Change Password',
                        'icon': 'fas fa-edit',
                        'btn_class': 'btn-primary',
                        'confirm': None,
                    },
                },
                bulk_actions_url=reverse('cis:teacher_bulk_actions'),
                filter_form_selector='#instructors_filter',
            ),
            'instructor_dangling_table': build_instructor_dangling_table_config(
                variant='instructor_dangling_index',
                api_url='/ce/api/instructor-dangling?format=datatables',
                bulk_actions={
                    'revoke_access': {
                        'label': 'Remove Instructor Access',
                        'icon': 'fas fa-user-slash',
                        'btn_class': 'btn-primary',
                        'confirm': 'Remove instructor access from the '
                                   'selected account(s)? Their other roles are unchanged.',
                        'method': 'POST',
                    },
                    'delete_account': {
                        'label': 'Delete Account',
                        'icon': 'fas fa-trash-alt',
                        'btn_class': 'btn-danger',
                        'confirm': 'Permanently delete the selected account(s)? Only accounts '
                                   'with no other roles and no references elsewhere are '
                                   'deleted; the rest are skipped and reported.',
                        'method': 'POST',
                    },
                },
                bulk_actions_url=reverse('cis:instructor_do_dangling_bulk_action'),
            ),
        }
    )

def delete_teacher_upload(request):
    upload_id = request.GET.get('upload_id')

    upload = get_object_or_404(
        TeacherUpload,
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

def import_instructors_from_file(request):
    """Handle CSV upload for instructor import; returns a results CSV."""
    form = InstructorCSVUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded = request.FILES.get('file').read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded))
        result = Teacher.import_from_csv(reader)

        if result['status'] == 'success':
            if not result['records']:
                messages.add_message(
                    request, messages.WARNING,
                    'The uploaded file contained no data rows.',
                    'list-group-item-warning')
                return redirect('cis:instructor_add_new')

            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = \
                'attachment; filename="instructor_import_results.csv"'
            writer = csv.writer(response)
            writer.writerow(result['records'][0].keys())
            for row in result['records']:
                writer.writerow(row.values())
            return response

        messages.add_message(
            request, messages.SUCCESS,
            'There was an error processing the file.' + result.get('message', ''),
            'list-group-item-danger')
        return redirect('cis:instructor_add_new')

    messages.add_message(
        request, messages.SUCCESS,
        'Please choose a valid CSV file.',
        'list-group-item-danger')
    return redirect('cis:instructor_add_new')


def download_instructor_template(request):
    """Download a blank CSV template with the correct instructor headers."""
    from cis.services.importers import InstructorRow

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = \
        'attachment; filename="instructor_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(InstructorRow.csv_headers())
    return response


def add_new(request):
    '''
    Add new page
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/teachers/teacher_add_new.html'

    if request.method == 'POST':
        if request.POST.get('upload_file') == 'Import Instructors':
            return import_instructors_from_file(request)

        form = TeacherForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            try:
                user = CustomUser()
                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.email = form.cleaned_data['email']
                user.username = form.cleaned_data['email'].lower()
                user.alt_email = form.cleaned_data['alt_email']
                user.secondary_email = form.cleaned_data['secondary_email']
                user.primary_phone = form.cleaned_data['primary_phone']
                user.secondary_phone = form.cleaned_data['secondary_phone']
                user.alt_phone = form.cleaned_data['alt_phone']
                user.psid = form.cleaned_data.get('psid', '')

                user.address1 = form.cleaned_data['address1']
                user.city = form.cleaned_data['city']
                user.state = form.cleaned_data['state']
                user.postal_code = form.cleaned_data['postal_code']

                #check if user email is already in the system
                if not CustomUser.objects.filter(email=form.cleaned_data['email']).exists():
                    user.save()
                else:
                    user = CustomUser.objects.get(email=form.cleaned_data['email'])

                    user.first_name = form.cleaned_data['first_name']
                    user.last_name = form.cleaned_data['last_name']
                    user.email = form.cleaned_data['email']
                    user.username = form.cleaned_data['email'].lower()
                    user.alt_email = form.cleaned_data['alt_email']
                    user.secondary_email = form.cleaned_data['secondary_email']
                    user.primary_phone = form.cleaned_data['primary_phone']
                    user.secondary_phone = form.cleaned_data['secondary_phone']
                    user.alt_phone = form.cleaned_data['alt_phone']
                    user.psid = form.cleaned_data.get('psid', '')

                    user.address1 = form.cleaned_data['address1']
                    user.city = form.cleaned_data['city']
                    user.state = form.cleaned_data['state']
                    user.postal_code = form.cleaned_data['postal_code']

                record = Teacher(user=user)
                record.save()

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
                return redirect('cis:instructor', record_id=record.id) #d
            except IntegrityError:
                form._errors['email'] = ['Sorry, an instructor account with this email already exists']

        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = TeacherForm()

    from cis.services.importers import InstructorRow as _InstructorRow
    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'page_title': "Add New",
            'labels': {
                'all_items': 'All Instructors'
            },
            'urls': {
                'add_new': 'cis:instructor_add_new',
                'all_items': 'cis:instructors'
            },
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'faculty', 'instructors'),
            'upload_form': InstructorCSVUploadForm(),
            'schema_fields': _InstructorRow.field_definitions(),
            'required_header': _InstructorRow.csv_headers(),
        })

def tab(request, record_id, tab_slug):
    """Render a single Teacher detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(Teacher, pk=record_id)
    return teacher_tabs.render_tab(request, record, tab_slug)


from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/teachers/teacher.html'    
    record = get_object_or_404(Teacher, pk=record_id)

    file_form = TeacherUploadForm(teacher=record)

    ed_bg_form = EdBgForm(user=record.user)
    migration_form = MigrateForm(record)

    form = TeacherForm(initial={
        'first_name':record.user.first_name,
        'last_name':record.user.last_name,
        'email':record.user.email,
        'username':record.user.username,
        'alt_email':record.user.alt_email,
        'secondary_email':record.user.secondary_email,
        'primary_phone': record.user.primary_phone,
        'secondary_phone': record.user.secondary_phone,
        'alt_phone': record.user.alt_phone,
        'psid': record.user.psid,
        'address1': record.user.address1,
        'city': record.user.city,
        'state': record.user.state,
        'postal_code': record.user.postal_code,
    })

    if request.method == 'POST':

        if request.POST.get('action') == 'migrate_position':
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
            file_form = TeacherUploadForm(
                record,
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
                return redirect('cis:instructor', record_id=record_id)
        elif request.POST.get('action') == 'edit_ed_bg':
            ed_bg_form = EdBgForm(
                record.user,
                request.POST
            )

            if ed_bg_form.is_valid():
                ed_bg_form.save(record.user)

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully saved educational background',
                    'list-group-item-success'
                )
                return redirect('cis:instructor', record_id=record_id)
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Please correct the errors and try again. ' + mark_safe(ed_bg_form.errors),
                    'list-group-item-warning'
                )
        else:
            form = TeacherForm(request.POST)

            if form.is_valid():
                try:
                    user = CustomUser.objects.get(pk=record.user.id)

                    user.first_name = form.cleaned_data['first_name']
                    user.last_name = form.cleaned_data['last_name']
                    user.email = form.cleaned_data['email']
                    user.username = form.cleaned_data['username'].lower()
                    user.alt_email = form.cleaned_data['alt_email']
                    user.secondary_email = form.cleaned_data['secondary_email']
                    user.primary_phone = form.cleaned_data['primary_phone']
                    user.secondary_phone = form.cleaned_data['secondary_phone']
                    user.alt_phone = form.cleaned_data['alt_phone']
                    user.psid = form.cleaned_data.get('psid', '')

                    user.address1 = form.cleaned_data['address1']
                    user.city = form.cleaned_data['city']
                    user.state = form.cleaned_data['state']
                    user.postal_code = form.cleaned_data['postal_code']

                    user.save()

                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Successfully updated record',
                        'list-group-item-success') 
                    return redirect('cis:instructor', record_id=record_id)
                except IntegrityError:
                    form._errors['email'] = ['An account with this email/username already exists.']
    

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Instructor Details",
            'labels': {
                'all_items': 'All Instructors'
            },
            'urls': {
                'add_new': 'cis:instructor_add_new',
                'all_items': 'cis:instructors'
            },
            'record': record,
            'menu': draw_menu(cis_menu, 'instructors', 'instructors'),
            'detail_tabs': teacher_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse('cis:instructor_tab', args=[record.id, slug]),
            ),
        })

def add_new_highschool(request):
    '''
    Add new highschool to teacher
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/teachers/manage_highschool.html'
    
    record = None
    id = request.GET.get('id')
    if id and id != '-1':
        record = TeacherHighSchool.objects.get(
            pk=id
        )

    if request.method == 'POST':
        form = TeacherHighSchoolForm(
            request.POST.get('id', '-1'),
            '-1',
            ajax,
            request.POST
        )

        if form.is_valid():
            try:
                record = form.save(request, commit=True)
                
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'success',
                        'message':'Successfully saved record',
                        'new_record_id':record.id,
                        'new_record_name':record.highschool.name,
                        'action': 'reload'
                    }
                    return JsonResponse(data)

            except IntegrityError as e:
                print(e)
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Looks like a duplicate entry'
                    }
                    return JsonResponse(data)
                form._errors['highschool'] = ['The role already exists for this high school']

            except TeacherHighSchool.DoesNotExist:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Invalid ID received'
                    }
                    return JsonResponse(data)
                form._errors['highschool'] = ['An invalid ID was received']
    else:       
        form = TeacherHighSchoolForm(
            id=request.GET.get('id', '-1'),
            teacher_id=request.GET.get('parent'),
            ajax=ajax
        )

        teacher = get_object_or_404(
            Teacher,
            pk=request.GET.get('parent')
        )

        
    return render(
        request,
        template, {
            'form': form,
            'teacher': teacher,
            'ajax': ajax,
            'record': record,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'faculty', 'instructors')
        })

@require_POST
def delete_record(request, record_id):
    record = get_object_or_404(Teacher, pk=record_id)
    user = record.user
    try:
        Teacher.delete_record(record)
    except Exception as e:
        data = {
            'status': 'error',
            'message': 'Unable to delete record. ' + str(e),
            'action': ''
        }
        return JsonResponse(data, status=400)

    # The instructor role is revoked only if staff say so, from the follow-up
    # prompt this response drives. The account is never deleted here.
    from cis.services.instructor_role import INSTRUCTOR
    from cis.services.role_access import has_remaining_records

    revocable = not has_remaining_records(INSTRUCTOR, user)

    return JsonResponse({
        'status': 'success',
        'message': 'Successfully deleted record',
        'action': 'reload',
        'instructor_role_revocable': revocable,
        'instructor_name': f'{user.first_name} {user.last_name}'.strip(),
        'other_roles': [r for r in user.get_roles() if r != 'instructor'],
        'revoke_url': str(reverse('cis:revoke_instructor_role', args=[user.id])),
        'redirect': str(reverse('cis:instructors')),
    })


@require_POST
def revoke_instructor_role(request, user_id):
    """Remove the instructor role for a user who holds no Teacher record.

    Called from the prompt that follows an instructor delete, and from the
    Dangling Accounts tab for anyone that prompt was declined or missed for.
    """
    from cis.services.instructor_role import INSTRUCTOR
    from cis.services.role_access import revoke_access

    user = get_object_or_404(CustomUser, pk=user_id)
    name = f'{user.first_name} {user.last_name}'.strip()

    if not revoke_access(INSTRUCTOR, user):
        return JsonResponse({
            'status': 'error',
            'message': f'{name} still has an instructor record. '
                       'Instructor access was left in place.',
        })

    retained = [r for r in user.get_roles()]
    message = f'{name} no longer has instructor access.'
    if retained:
        message += f' Their {", ".join(retained)} access is unchanged.'

    return JsonResponse({'status': 'success', 'message': message})

def delete_course_certificate(request, record_id):
    record = get_object_or_404(TeacherCourseCertificate, pk=record_id)

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

def delete_teacher_highschool(request, record_id):
    record = get_object_or_404(TeacherHighSchool, pk=record_id)

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

def add_new_course_certificate(request):
    '''
    Add new highschool course to teacher
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/teachers/manage_course_certificate.html'

    record = None
    id = request.GET.get('id')
    if id and id != '-1':
        record = TeacherCourseCertificate.objects.get(
            pk=id
        )

    if request.method == 'POST':
        id = request.POST.get('id')
        if id != '-1':
            record = TeacherCourseCertificate.objects.get(
                pk=id
            )
        teacher = get_object_or_404(Teacher, pk=request.POST.get('teacher'))
        form = TeacherCourseForm(
            request.POST.get('id'),
            teacher,
            request.POST.get('ajax'),
            request.POST
        )

        if form.is_valid():
            try:
                record = form.save(request, True)
                
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'success',
                        'message':'Successfully saved record',
                        'new_record_id':record.id,
                        'new_record_name':record.teacher_highschool.highschool.name,
                        'action': 'reload'
                    }
                    return JsonResponse(data)

            except IntegrityError:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Looks like a duplicate entry'
                    }
                    return JsonResponse(data)
                form._errors['highschool'] = ['The course already exists for this high school']

            except TeacherHighSchool.DoesNotExist:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Invalid ID received'
                    }
                    return JsonResponse(data)
                form._errors['highschool'] = ['An invalid ID was received']
    else:
        teacher = get_object_or_404(Teacher, pk=request.GET.get('parent'))
        form = TeacherCourseForm(
            id=request.GET.get('id'),
            teacher=teacher,
            ajax=ajax
        )

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'record': record,
            'teacher': teacher,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'faculty', 'instructors')
        })


def do_dangling_bulk_action(request):
    """Bulk actions for the Instructor Dangling Accounts tab.

    `ids[]` are CustomUser ids — an integer AutoField, unlike the UUID
    primary keys used elsewhere in this file, so the id guard below
    validates with int(), not uuid.UUID(). Both actions are POST-only: one
    drops a role, the other deletes an account. The unknown-action check
    runs before the POST-only check, so an unknown action arriving over GET
    cannot reach a mutation.
    """
    action = request.POST.get('action') or request.GET.get('action')
    ids = request.POST.getlist('ids[]') or request.GET.getlist('ids[]')

    if action not in ('revoke_access', 'delete_account'):
        return JsonResponse({
            'status': 'error',
            'message': 'Unknown action.',
        }, status=400)

    if request.method != 'POST':
        return JsonResponse({
            'status': 'error',
            'message': 'This action requires POST.',
        }, status=405)

    valid_ids = []
    for record_id in ids:
        try:
            valid_ids.append(int(record_id))
        except (ValueError, TypeError):
            continue

    from cis.services.instructor_role import INSTRUCTOR
    from cis.services.role_access import revoke_access

    users = CustomUser.objects.filter(id__in=valid_ids)

    if action == 'revoke_access':
        revoked = skipped = 0
        for user in users:
            if revoke_access(INSTRUCTOR, user):
                revoked += 1
            else:
                skipped += 1

        return JsonResponse({
            'status': 'success',
            'message': (
                f'{revoked} account(s) no longer have instructor access, '
                f'{skipped} skipped (they still hold a Teacher record).'
            ),
        })

    from django.db.models import ProtectedError

    deleted = skipped = errored = 0
    for user in users:
        # Only ever delete an account that this tab is responsible for: no
        # Teacher record, and no other role to keep it alive.
        if Teacher.objects.filter(user=user).exists():
            skipped += 1
            continue
        if [r for r in user.get_roles() if r != 'instructor']:
            skipped += 1
            continue
        try:
            user.delete()
            deleted += 1
        except ProtectedError:
            # The account is referenced elsewhere (notes they authored,
            # records they created) via a PROTECT foreign key. This is the
            # ordinary, explainable reason a dangling account cannot be
            # deleted, so it is counted with the other skips.
            skipped += 1
        except Exception:
            # An unexpected failure, not one of the well-understood skip
            # cases above. Count and log it separately so the operator isn't
            # told the wrong reason for the failure, and it doesn't vanish
            # the way the original bug swallowed ProtectedError silently.
            logger.exception(
                'Unexpected error deleting CustomUser %s', user.pk)
            errored += 1

    message = (
        f'{deleted} account(s) deleted, {skipped} skipped '
        '(skipped accounts hold other roles, have a Teacher record, '
        'or are referenced elsewhere).'
    )
    if errored:
        message += f' {errored} account(s) failed unexpectedly.'

    return JsonResponse({
        'status': 'success',
        'message': message,
    })
