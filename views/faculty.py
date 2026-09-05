import io
import csv
import logging
import uuid

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

from cis.serializers.faculty import (
    FacultySerializer,
    CourseAdministratorSerializer,
    DanglingFacultySerializer,
)

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

from cis.views.eager import (
    eager_queryset,
    with_course_administrator_related,
)

logger = logging.getLogger(__name__)


@eager_queryset(with_course_administrator_related)
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
        qs = FacultyCoordinator.objects.select_related(
            'user', 'department',
        ).order_by('user__last_name', 'user__first_name')

        # Status filter for the All Faculty tab's filter form. Guarded: an
        # unrecognized value (typo, tampering) narrows to zero rows via a
        # plain CharField comparison rather than raising; empty/"all" means
        # no filter.
        status = self.request.GET.get('status', '').strip()
        if status and status.lower() != 'all':
            qs = qs.filter(status__iexact=status)
        return qs


class DanglingFacultyViewSet(viewsets.ReadOnlyModelViewSet):
    """Accounts left in the faculty group with no FacultyCoordinator record.

    They appear on no other tab: the faculty tabs are driven by
    FacultyCoordinator records, which these users no longer have. This is
    the only place staff can reach them.

    FacultyCoordinator's docstring notes the model is "not used any more" --
    this endpoint is audit-and-revoke only. There is no delete-record path
    for FacultyCoordinator, and this view does not add one.
    """
    serializer_class = DanglingFacultySerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        from cis.services.role_access import dangling_users
        from cis.services.faculty_role import FACULTY

        return dangling_users(FACULTY)


def index(request):
    '''
    Teacher search and index page for staff
    '''
    from cis.services.table_configs import get_table_config
    build_faculty_coords_table_config = get_table_config('faculty_coords_table').build_config
    build_faculty_table_config = get_table_config('faculty_table').build_config
    build_faculty_dangling_table_config = get_table_config('faculty_dangling_table').build_config

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
            # Drive the All Faculty status filter from the model rather than
            # hardcoding the options in the template: a new status value then
            # appears in the dropdown automatically instead of being silently
            # unfilterable until someone notices.
            'faculty_status_options': FacultyCoordinator.STATUS_OPTIONS,
            'accessible_campuses': get_accessible_campuses(request.user),
            'default_campus': get_default_campus(request.user),
            'faculty_table': build_faculty_table_config(
                variant='faculty_index',
                api_url='/ce/api/faculty?format=datatables',
                details_prefix='/ce/faculty_coordinator/',
                bulk_actions={
                    'delete': {
                        'label': 'Delete',
                        'icon': 'fas fa-trash',
                        'btn_class': 'btn-danger',
                        'method': 'POST',
                        'confirm': (
                            'Delete the selected faculty coordinator record(s) '
                            'and their course-coordinator rows and notes? '
                            'The user account is NOT deleted.'
                        ),
                    },
                },
                bulk_actions_url=reverse('cis:faculty_bulk_actions'),
                filter_form_selector='#all_faculty_filter',
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
                    'delete_course_administrator': {
                        'label': 'Delete',
                        'icon': 'fas fa-trash',
                        'btn_class': 'btn-danger',
                        'method': 'POST',
                        'confirm': (
                            'Delete the selected course assignment(s)? '
                            'The faculty coordinator record and the user '
                            'account are NOT deleted.'
                        ),
                    },
                },
                bulk_actions_url=reverse('cis:faculty_bulk_actions'),
                filter_form_selector='#faculty_filter',
            ),
            'faculty_dangling_table': build_faculty_dangling_table_config(
                variant='faculty_dangling_index',
                api_url='/ce/api/faculty-dangling?format=datatables',
                bulk_actions={
                    'revoke_access': {
                        'label': 'Remove Faculty Access',
                        'icon': 'fas fa-user-slash',
                        'btn_class': 'btn-primary',
                        'confirm': 'Remove faculty access from the '
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
                bulk_actions_url=reverse('cis:faculty_do_dangling_bulk_action'),
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

    if action not in ('delete', 'delete_course_administrator'):
        # Checked before either delete branch's own POST-only guard so an
        # unknown action over GET is rejected here and never reaches any
        # mutation.
        return JsonResponse({
            'status': 'error',
            'message': 'Unknown action.',
        }, status=400)

    if request.method != 'POST':
        return JsonResponse({
            'status': 'error',
            'message': 'Delete requires POST.',
        }, status=405)

    if action == 'delete':
        return do_faculty_coordinator_bulk_delete(request)

    return do_course_administrator_bulk_delete(request)


def do_faculty_coordinator_bulk_delete(request):
    """Delete selected FacultyCoordinator records.

    ids[] are FacultyCoordinator ids, which are UUIDs -- unlike CustomUser
    pks, which are integers. The account is never deleted; the `faculty`
    group is revoked as a separate explicit step once no FacultyCoordinator
    record remains for the user -- cis.services.role_access.revoke_access.
    """
    from django.db.models import ProtectedError

    from cis.services.faculty_role import FACULTY
    from cis.services.role_access import revoke_access

    ids = request.POST.getlist('ids[]')

    valid_ids = []
    for record_id in ids:
        try:
            valid_ids.append(uuid.UUID(str(record_id)))
        except (ValueError, AttributeError, TypeError):
            # Malformed id (e.g. a stale/forged value) -- skip rather than
            # 500ing on a bad UUID.
            continue

    deleted = left_in_place = errored = 0
    for record_id in valid_ids:
        try:
            record = FacultyCoordinator.objects.get(pk=record_id)
        except FacultyCoordinator.DoesNotExist:
            continue

        user = record.user
        try:
            FacultyCoordinator.delete_record(record)
        except ProtectedError:
            # A PROTECT child was never cleared. The well-understood, ordinary
            # reason a delete cannot proceed -- counted separately from an
            # unexpected failure below so the operator isn't told the wrong
            # reason for the failure.
            left_in_place += 1
            continue
        except Exception:
            logger.exception(
                'Unexpected error deleting FacultyCoordinator %s', record_id)
            errored += 1
            continue

        deleted += 1

        # The account itself is never deleted; revoke_access only drops the
        # faculty group once no FacultyCoordinator record remains for it.
        revoke_access(FACULTY, user)

    message = f'Deleted {deleted} faculty coordinator record(s).'
    if left_in_place:
        message += f' {left_in_place} record(s) left in place (still referenced elsewhere).'
    if errored:
        message += f' {errored} record(s) failed unexpectedly.'

    return JsonResponse({
        'status': 'success',
        'message': message,
        'action': 'reload_page',
    })


def do_course_administrator_bulk_delete(request):
    """Delete selected CourseAdministrator records -- a course *assignment*,
    not the coordinator record or the account.

    ids[] are CourseAdministrator ids, which are UUIDs -- like
    FacultyCoordinator ids above, unlike the CustomUser integer ids
    do_dangling_bulk_action (below) uses.

    Reuses the same op as the single-record path,
    cis.views.course.delete_course_administrator_role: record.delete().
    CourseAdministrator.user is a PROTECT FK *from* this row *to* CustomUser
    (not the other way around), and nothing else points at CourseAdministrator
    with PROTECT, so deleting this row never cascades into the
    FacultyCoordinator, the CustomUser, or the Course -- only the one
    course-assignment row is removed. The ProtectedError guard below is kept
    for parity with every other bulk-delete in this module, in case a future
    relation adds one.
    """
    from django.db.models import ProtectedError

    ids = request.POST.getlist('ids[]')

    valid_ids = []
    for record_id in ids:
        try:
            valid_ids.append(uuid.UUID(str(record_id)))
        except (ValueError, AttributeError, TypeError):
            # Malformed id (e.g. a stale/forged value) -- skip rather than
            # 500ing on a bad UUID.
            continue

    deleted = left_in_place = errored = 0
    for record_id in valid_ids:
        try:
            record = CourseAdministrator.objects.get(pk=record_id)
        except CourseAdministrator.DoesNotExist:
            continue

        try:
            record.delete()
        except ProtectedError:
            # The well-understood, ordinary reason a delete cannot proceed --
            # counted separately from an unexpected failure below so the
            # operator isn't told the wrong reason for the failure.
            left_in_place += 1
            continue
        except Exception:
            logger.exception(
                'Unexpected error deleting CourseAdministrator %s', record_id)
            errored += 1
            continue

        deleted += 1

    message = f'Deleted {deleted} course assignment(s).'
    if left_in_place:
        message += f' {left_in_place} record(s) left in place (still referenced elsewhere).'
    if errored:
        message += f' {errored} record(s) failed unexpectedly.'

    return JsonResponse({
        'status': 'success',
        'message': message,
        'action': 'reload_page',
    })

def do_dangling_bulk_action(request):
    """Bulk actions for the Faculty Dangling Accounts tab.

    `ids[]` are CustomUser ids — an integer AutoField, unlike the UUID
    primary keys used by do_faculty_coordinator_bulk_delete above (which
    operates on FacultyCoordinator ids). The id guard below validates with
    int(), not uuid.UUID(). Both actions are POST-only: one drops the
    faculty group, the other deletes an account. The unknown-action check
    runs before the POST-only check, so an unknown action arriving over GET
    cannot reach a mutation.

    delete_account here removes only a bare CustomUser with no
    FacultyCoordinator record and no other role -- it never deletes a
    FacultyCoordinator record. FacultyCoordinator has no delete path in this
    plan; see cis.views.faculty.do_faculty_coordinator_bulk_delete for that.
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

    from cis.services.faculty_role import FACULTY
    from cis.services.role_access import revoke_access

    users = CustomUser.objects.filter(id__in=valid_ids)

    if action == 'revoke_access':
        revoked = skipped = 0
        for user in users:
            if revoke_access(FACULTY, user):
                revoked += 1
            else:
                skipped += 1

        return JsonResponse({
            'status': 'success',
            'message': (
                f'{revoked} account(s) no longer have faculty access, '
                f'{skipped} skipped (they still hold a FacultyCoordinator '
                'record).'
            ),
        })

    from django.db.models import ProtectedError

    deleted = skipped = errored = 0
    for user in users:
        # Only ever delete an account that this tab is responsible for: no
        # FacultyCoordinator record, and no other role to keep it alive.
        if FacultyCoordinator.objects.filter(user=user).exists():
            skipped += 1
            continue
        if [r for r in user.get_roles() if r != 'faculty']:
            skipped += 1
            continue
        try:
            user.delete()
            deleted += 1
        except ProtectedError:
            # The account is referenced elsewhere via a PROTECT foreign key.
            # This is the ordinary, explainable reason a dangling account
            # cannot be deleted, so it is counted with the other skips.
            skipped += 1
        except Exception:
            # An unexpected failure, not one of the well-understood skip
            # cases above. Count and log it separately so the operator isn't
            # told the wrong reason for the failure.
            logger.exception(
                'Unexpected error deleting CustomUser %s', user.pk)
            errored += 1

    message = (
        f'{deleted} account(s) deleted, {skipped} skipped '
        '(skipped accounts hold other roles, have a FacultyCoordinator '
        'record, or are referenced elsewhere).'
    )
    if errored:
        message += f' {errored} account(s) failed unexpectedly.'

    return JsonResponse({
        'status': 'success',
        'message': message,
    })


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
