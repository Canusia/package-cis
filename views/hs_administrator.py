import csv
import io
import uuid
from datetime import datetime

from django.db import IntegrityError
from django.db.models import Q, Count
from django.conf import settings

from django.urls import reverse_lazy, reverse

from django.contrib import messages
from django.views.decorators.clickjacking import xframe_options_exempt
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
    HSAdministratorAccessRequest
)

from cis.forms.utils import EmailForm
from cis.utils import user_has_cis_role
from cis.services.table_configs import get_table_config
build_access_requests_table_config = get_table_config('access_requests_table').build_config

from cis.forms.highschool import (
    HSAdministratorForm, HSAdministratorAddForm,
    HSAdministratorPositionForm,
    HSAdminAccessRequestModelForm, HSMemberUploadForm
)

from cis.models.note import HSAdministratorNote
from cis.menu import cis_menu, draw_menu
build_hs_admins_table_config = get_table_config('hs_admins_table').build_config
build_hs_admin_people_table_config = get_table_config('hs_admin_people_table').build_config
from myce.component_registry.hs_administrator import hs_administrator_tabs
from myce.component_registry.access_request import access_request_tabs

from ..serializers.highschool import (
    HighSchoolAdministratorSerializer,
    HSAdministratorAccessRequestSerializer
)
from ..serializers.highschool_admin import (
    HSAdministratorSerializer
)
from cis.utils import CIS_user_only

class HSAdministratorPositionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HighSchoolAdministratorSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        records = HSAdministratorPosition.objects.all()

        hsadmin_id = self.request.GET.get('hsadmin')
        if hsadmin_id:
            # Guard a client-supplied hsadmin: a non-UUID value would raise
            # ValidationError -> 500 in the filter below. Treat a
            # present-but-malformed id as "no match". (Same idiom as the
            # PT-1 term_id guard and the TeacherUpload teacher_id guard.)
            try:
                uuid.UUID(str(hsadmin_id))
            except (ValueError, AttributeError, TypeError):
                return HSAdministratorPosition.objects.none()
            records = records.filter(hsadmin__id=hsadmin_id)

        return records

class HSAdministratorViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HSAdministratorSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        # school_count must be a real annotation, not a SerializerMethodField:
        # rest_framework_datatables orders and filters server-side using the
        # column's data-name, and a non-ORM path raises FieldError -> 500.
        return HSAdministrator.objects.select_related('user').annotate(
            school_count=Count('hsadministratorposition')
        )

class HSAdministratorAccessRequestViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HSAdministratorAccessRequestSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        
        status = self.request.GET.get('status')

        records = HSAdministratorAccessRequest.objects.all()

        if status:
            records = records.filter(
                status__iexact=status
            )
        return records
        
def access_requests(request):
    """
    Show all requests to CE Staff
    """
    '''
    HS Admin search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'highschools', 'access_requests')
    template = 'cis/hs_admin/access_requests.html'
    
    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'High Schools',
            'api_url': '/ce/api/hs-administrator-access-request?format=datatables',
            'urls': {
                'details_prefix': '/ce/highschool_admin/access_request/',
                'add_new': 'cis:hs_add_new'
            },
            'access_requests_table': build_access_requests_table_config(
                variant='access_requests_index',
                api_url='/ce/api/hs-administrator-access-request?format=datatables',
                details_prefix='/ce/highschool_admin/access_request/',
            ),
        }
    )

def delete_record(request, record_id):
    record = get_object_or_404(HSAdministrator, pk=record_id)
    user = record.user

    try:
        HSAdministratorNote.objects.filter(
            hsadmin=record
        ).delete()

        HSAdministrator.delete_record(record)
    except Exception as e:
        return JsonResponse({
            'message': 'Unable to delete record' + str(e),
            'status': 'error'
        }, status=400)

    # The highschool_admin role is revoked only if staff say so, from the
    # follow-up prompt this response drives. The account is never deleted here.
    from cis.services.hs_admin_role import has_remaining_hs_admin_roles

    revocable = not has_remaining_hs_admin_roles(user)

    return JsonResponse({
        'message': 'Successfully deleted record',
        'status': 'success',
        'hs_admin_role_revocable': revocable,
        'admin_name': f'{user.first_name} {user.last_name}'.strip(),
        'other_roles': [r for r in user.get_roles() if r != 'highschool_admin'],
        'revoke_url': str(reverse('cis:revoke_hs_admin_role', args=[user.id])),
        'redirect': str(reverse_lazy('cis:hs_admins')),
    })


@require_POST
def revoke_hs_admin_role(request, user_id):
    """Remove the highschool_admin role for a user who holds no roles left.

    Called from the prompt that follows an administrator delete, and from the
    Dangling Accounts tab for anyone that prompt was declined or missed for.
    """
    from cis.services.hs_admin_role import revoke_hs_admin_access

    user = get_object_or_404(CustomUser, pk=user_id)
    name = f'{user.first_name} {user.last_name}'.strip()

    if not revoke_hs_admin_access(user):
        return JsonResponse({
            'status': 'error',
            'message': f'{name} still holds a high school role. '
                       'High school administrator access was left in place.',
        })

    retained = [r for r in user.get_roles()]
    message = f'{name} no longer has high school administrator access.'
    if retained:
        message += f' Their {", ".join(retained)} access is unchanged.'

    return JsonResponse({'status': 'success', 'message': message})

@xframe_options_exempt
def delete_access_request(request, record_id):
    record = get_object_or_404(HSAdministratorAccessRequest, pk=record_id)
    try:
        record.delete()

        data = {
            'status':'success',
            'message':'Successfully deleted record',
            'action': 'redirect',
            'location': str(
                reverse_lazy(
                    'cis:hs_admin_access_requests'
                )
            )
        }
    except Exception as e:
        data = {
            'status':'error',
            'message':'Unable to complete request.' + str(e),
        }
    return JsonResponse(data)

def access_request_tab(request, record_id, tab_slug):
    """Render a single Access Request detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(HSAdministratorAccessRequest, pk=record_id)
    return access_request_tabs.render_tab(request, record, tab_slug)


@xframe_options_exempt
def access_request(request, record_id):
    """
    Shows details about request
    """
    template = 'cis/hs_admin/access_request.html'
    record = get_object_or_404(HSAdministratorAccessRequest, pk=record_id)

    if request.method == 'POST':
        form = HSAdminAccessRequestModelForm(
            request.POST,
            instance=record,
            request=request)

        if form.is_valid():
            record = form.save()
            
            if record.status == 'Approved':                    
                record.grant_access(form.cleaned_data)

            record.send_email()
            
            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated request',
                'list-group-item-success') 
            return redirect('cis:hs_admin_access_request', record_id=record_id)
        else:
            messages.add_message(
                request,
                messages.SUCCESS,
                'Unable to complete request - ' + str(form.errors),
                'list-group-item-warning') 
            return redirect('cis:hs_admin_access_request', record_id=record_id)

    form = HSAdminAccessRequestModelForm(instance=record, request=request)
    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'highschools', 'access_requests'),
            'record': record,
            'detail_tabs': access_request_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse('cis:access_request_tab', args=[record.id, slug]),
            ),
        })

def submit_new_request(request):
    """
    Handle new request submission in the frontend
    """
    template = 'cis/index/highschool_admin_request_access.html'
    context = {}
    if request.method == 'POST':
        form = HSAdminAccessRequestModelForm(request.POST, request=request)

        if form.is_valid():
            record = form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                'Thank you for submitting your request. We will contact you once we have processed your request.',
                'list-group-item-success'
            )
            return redirect('highschool_admin_index')
    else:
        form = HSAdminAccessRequestModelForm(request=request)

    context['form'] = form
    return render(request, template, context)
submit_new_request.login_required = False

# def delete_record(request, record_id):
#     record = get_object_or_404(HSAdministrator, pk=record_id)

#     try:
#         HSAdministratorPosition.objects.filter(
#             hsadmin=record
#         ).delete()

#         record.delete()

#         data = {
#             'status':'success',
#             'message':'Successfully deleted record',
#             'action': 'reload'
#         }
#     except Exception as e:
#         data = {
#             'status':'error',
#             'message':'Unable to complete request.' + str(e),
#         }
#     return JsonResponse(data)

def delete_role(request, record_id):
    record = get_object_or_404(HSAdministratorPosition, pk=record_id)

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

def get_password_reset_link(request):
    record_id = request.GET.get('id')
    record = get_object_or_404(HSAdministrator, pk=record_id)

    url = record.user.get_password_reset_link()

    return JsonResponse({
        'url': url})

def tab(request, record_id, tab_slug):
    """Render a single HS Administrator detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(HSAdministrator, pk=record_id)
    return hs_administrator_tabs.render_tab(request, record, tab_slug)


@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/hs_admin/detail.html'    
    record = get_object_or_404(HSAdministrator, pk=record_id)

    if request.method == 'POST':
        form = HSAdministratorForm(request.POST)

        if form.is_valid():
            try:
                user = CustomUser.objects.get(pk=record.user.id)

                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.email = form.cleaned_data['email']
                user.primary_phone = form.cleaned_data['primary_phone']
                user.secondary_phone = form.cleaned_data.get('secondary_phone')

                user.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:hs_admin', record_id=record_id)
            except IntegrityError:
                form._errors['email'] = ['An account with this email already exists.']
    else:
        form = HSAdministratorForm(initial={
            'first_name':record.user.first_name,
            'last_name':record.user.last_name,
            'email':record.user.email,
            'primary_phone': record.user.primary_phone,
            'secondary_phone': record.user.secondary_phone
        })

    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'highschools', 'school_administrators'),
            'record': record,
            'detail_tabs': hs_administrator_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse('cis:hs_admin_tab', args=[record.id, slug]),
            ),
        })

def add_new_role(request):
    '''
    Add new role to hs administrator
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/hs_admin/manage_role.html'

    record = None
    if request.method == 'POST':
        
        form = HSAdministratorPositionForm(
            id=request.POST.get('id'),
            data=request.POST
        )

        if form.is_valid():
            try:
                record = form.save(request) 

                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'success',
                        'message':'Successfully saved record',
                        'new_record_id':record.id,
                        'new_record_name':record.hsadmin.user.first_name,
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
                form._errors['highschool'] = ['The role already exists for this high school']

            except HSAdministratorPosition.DoesNotExist:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Invalid role ID received'
                    }
                    return JsonResponse(data)
                form._errors['highschool'] = ['An invalid ID was received']
    else:
        initial = {
            'hs_admin':request.GET.get('parent'),
            'id': '-1',
            'ajax': ajax
        }

        if request.GET.get('id', '-1') != '-1':
            record = HSAdministratorPosition.objects.get(pk=request.GET.get('id'))
            initial['id'] = record.id
            initial['highschool'] = record.highschool.id
            initial['status'] = record.status
            initial['position'] = record.position.id

            initial['manage_student_recommendation'] = record.meta.get('manage_student_recommendation')

            if record.since:
                initial['since'] = record.since.strftime("%m/%d/%Y")

        form = HSAdministratorPositionForm(
            id=request.GET.get('id'),
            initial=initial
        )

    if not user_has_cis_role(request.user):
        record = None

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'record': record,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'highschools', 'school_administrators')
        })

def import_hs_members_from_file(request):
    """Handle CSV file upload for HS Member import."""
    from cis.services.importers import HSMemberRow

    form = HSMemberUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded_file))

        result = HSAdministrator.import_from_csv(reader)
        if result['status'] == 'success':
            if not result['records']:
                messages.add_message(
                    request,
                    messages.WARNING,
                    'The uploaded file contained no data rows.',
                    'list-group-item-warning')
                return redirect('cis:hs_admin_add_new')

            file_name = "hs_member_import_results.csv"
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
        return redirect('cis:hs_admin_add_new')


def download_hs_member_template(request):
    """Download a blank CSV template with the correct headers for HS Member import."""
    from cis.services.importers import HSMemberRow

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="hs_member_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(HSMemberRow.csv_headers())
    return response


def add_new(request):
    '''
    Add new page
    '''
    from cis.services.importers import HSMemberRow

    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/hs_admin/add_new.html'
    upload_form = HSMemberUploadForm()

    if request.method == 'POST':
        if request.POST.get('upload_file') == "Import HS Members":
            return import_hs_members_from_file(request)

        form = HSAdministratorAddForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            try:
                email = form.cleaned_data['email']

                hs_member = HSAdministrator.get_or_add(
                    email=email,
                    first_name=form.cleaned_data['first_name'],
                    last_name=form.cleaned_data['last_name'],
                    primary_phone=form.cleaned_data.get('primary_phone', ''),
                    middle_name=form.cleaned_data.get('middle_name', ''),
                    salutation=form.cleaned_data.get('salutation', ''),
                )

                if hs_member is None:
                    raise IntegrityError('Failed to create administrator record')

                # Process CEEB codes → position links
                ceeb_str = form.cleaned_data['ceeb']
                position_title = form.cleaned_data.get('position_title') or 'Primary Contact'
                status = form.cleaned_data.get('status') or 'Active'
                ceeb_errors = []

                for ceeb in ceeb_str.split(','):
                    ceeb = ceeb.strip()
                    if not ceeb:
                        continue
                    try:
                        highschool = HighSchool.objects.get(code=ceeb)
                        hs_position = HSPosition.get_or_add(name=position_title)
                        HSAdministratorPosition.get_or_add(
                            hsadmin=hs_member,
                            highschool=highschool,
                            position=hs_position,
                            status=status,
                        )
                    except HighSchool.DoesNotExist:
                        ceeb_errors.append(ceeb)

                if ceeb_errors:
                    form._errors['ceeb'] = [
                        f"High school(s) not found for CEEB code(s): {', '.join(ceeb_errors)}"
                    ]
                else:
                    if ajax == '1':
                        data = {
                            'status':'success',
                            'message':'Successfully added new record',
                            'new_record_id': str(hs_member.id),
                            'new_record_name': hs_member.user.first_name
                        }
                        return JsonResponse(data)

                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Successfully added record',
                        'list-group-item-success')
                    return redirect('cis:hs_admin', record_id=hs_member.id)
            except IntegrityError:
                form._errors['email'] = ['Sorry, an account with this email already exists']

        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = HSAdministratorAddForm()

    context = {
        'form': form,
        'ajax': ajax,
        'base_template': base_template,
        'menu': draw_menu(cis_menu, 'highschools', 'school_administrators')
    }

    if not ajax:
        context['upload_form'] = upload_form
        context['schema_fields'] = HSMemberRow.field_definitions()
        context['required_header'] = HSMemberRow.csv_headers()

    return render(request, template, context)

def index(request):
    '''
    HS Admin search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'highschools', 'school_administrators')
    template = 'cis/hs_admin/index.html'

    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'High School Administrators',
            'api_url': '/ce/api/hs-administrator?format=datatables',
            'roles_api_url': '/ce/api/hs-administrator-position?format=datatables',
            'urls': {
                'details_prefix': '/ce/highschool_admin/',
                'add_new': 'cis:hs_admin_add_new'
            },
            'hs_admins_table': build_hs_admins_table_config(
                variant='hs_admins_index',
                api_url='/ce/api/hs-administrator-position?format=datatables',
                details_prefix='/ce/highschool_admin/',
                bulk_actions={
                    'edit_status': {
                        'label': 'Edit Status',
                        'icon': 'fas fa-edit',
                        'btn_class': 'btn-primary',
                        'confirm': None,
                    },
                    'delete': {
                        'label': 'Delete',
                        'icon': 'fas fa-trash-alt',
                        'btn_class': 'btn-danger',
                        'confirm': 'Are you sure you want to delete the selected role(s)? '
                                   'The administrator accounts are not removed.',
                        'method': 'POST',
                    },
                    'toggle_student_recommendation': {
                        'label': 'Toggle Student Rec.',
                        'icon': 'fas fa-edit',
                        'btn_class': 'btn-primary',
                        'confirm': 'Are you sure you want to toggle student recommendation on the selected records?',
                    },
                    'change_password': {
                        'label': 'Change Password',
                        'icon': 'fas fa-edit',
                        'btn_class': 'btn-primary',
                        'confirm': None,
                    },
                    'password_reset_link': {
                        'label': 'Generate Reset Link',
                        'icon': 'fas fa-link',
                        'btn_class': 'btn-primary',
                        'confirm': None,
                    },
                },
                bulk_actions_url=reverse('cis:hs_admin_do_bulk_action'),
            ),
            'hs_admin_people_table': build_hs_admin_people_table_config(
                variant='hs_admin_people_index',
                api_url='/ce/api/hs-administrator?format=datatables',
                details_prefix='/ce/highschool_admin/',
                bulk_actions={
                    'delete': {
                        'label': 'Delete',
                        'icon': 'fas fa-trash-alt',
                        'btn_class': 'btn-danger',
                        'confirm': 'Are you sure you want to delete the selected administrator(s)? '
                                   'Administrators who still hold roles are skipped.',
                        'method': 'POST',
                    },
                    'change_password': {
                        'label': 'Change Password',
                        'icon': 'fas fa-edit',
                        'btn_class': 'btn-primary',
                        'confirm': None,
                    },
                    'password_reset_link': {
                        'label': 'Generate Reset Link',
                        'icon': 'fas fa-link',
                        'btn_class': 'btn-primary',
                        'confirm': None,
                    },
                },
                bulk_actions_url=reverse('cis:hs_admin_do_person_bulk_action'),
            ),
        }
    )

def do_bulk_action(request):
    action = request.GET.get('action')

    if request.method == 'POST':
        action = request.POST.get('action')

    ids = request.GET.getlist('ids[]')

    if action in ['toggle_status', 'toggle_student_recommendation']:
        for id in ids:
            try:
                record = HSAdministratorPosition.objects.get(pk=id)
                if action == 'toggle_status':
                    record.toggle_status()
                if action == 'toggle_student_recommendation':
                    record.toggle_student_recommendation()
            except:
                ...

        data = {
            'status': 'success',
            'message': 'Successfully processed request'
        }

        return JsonResponse(data)

    if action == 'edit_status':
        return manage_edit_status(request)

    if action == 'delete':
        if request.method != 'POST':
            # Deletion over GET would be CSRF-reachable from any page.
            return JsonResponse({
                'status': 'error',
                'message': 'Delete requires POST.',
            }, status=405)

        post_ids = request.POST.getlist('ids[]')
        deleted = 0
        failed = 0
        for record_id in post_ids:
            try:
                uuid.UUID(str(record_id))
            except (ValueError, AttributeError, TypeError):
                continue
            try:
                count, _ = HSAdministratorPosition.objects.filter(pk=record_id).delete()
                deleted += count
            except Exception:
                failed += 1
                continue

        if failed:
            message = f'Successfully deleted {deleted} role(s), {failed} failed.'
        else:
            message = f'Successfully deleted {deleted} role(s).'

        return JsonResponse({
            'status': 'success',
            'message': message,
        })

    if action == 'password_reset_link':
        valid_ids = []
        for record_id in ids:
            try:
                uuid.UUID(str(record_id))
            except (ValueError, AttributeError, TypeError):
                continue
            valid_ids.append(record_id)

        admin_ids = HSAdministratorPosition.objects.filter(
            id__in=valid_ids
        ).values_list('hsadmin__id', flat=True).distinct()

        admins = HSAdministrator.objects.filter(
            id__in=list(admin_ids)
        ).select_related('user')

        return render_reset_links(request, admins)

    if action == 'change_password':
        return manage_change_password(request)

def manage_edit_status(request):
    """Render (GET) or apply (POST) the bulk status change modal."""
    template = 'cis/hs_admin/edit_status.html'

    from cis.forms.highschool import BulkStatusChangeForm

    if request.method == 'POST':
        form = BulkStatusChangeForm(data=request.POST)

        if form.is_valid():
            updated, notes_created = form.save(request)
            return JsonResponse({
                'status': 'success',
                'message': f'Successfully updated {updated} record(s).',
                'action': 'reload_table',
            })

        return JsonResponse({
            'status': 'error',
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json(),
        }, status=400)

    ids = request.GET.getlist('ids[]')
    form = BulkStatusChangeForm(ids)

    return render(request, template, {
        'title': 'Edit Status',
        'form': form,
        'id': 'frm_bulk_status',
        'form_action': str(reverse('cis:hs_admin_do_bulk_action')),
        'status': 'display',
    })

def render_reset_links(request, admins):
    """Render the bulk password-reset-link modal for the given administrators."""
    rows = []
    for admin in admins:
        rows.append({
            'name': f"{admin.user.last_name}, {admin.user.first_name}",
            'email': admin.user.email,
            'link': admin.user.get_password_reset_link(),
        })

    rows.sort(key=lambda r: r['name'])

    return render(request, 'cis/hs_admin/reset_links.html', {
        'title': 'Password Reset Links',
        'rows': rows,
    })


def manage_change_password(request, admin_ids=None):
    template = 'cis/hs_admin/change_password.html'

    from cis.forms.highschool import BulkPasswordChangeForm
    if request.method == 'POST':

        form = BulkPasswordChangeForm(data=request.POST)

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

    if admin_ids is None:
        ids = request.GET.getlist('ids[]')
        admin_ids = HSAdministratorPosition.objects.filter(
            id__in=ids
        ).values_list('hsadmin__id', flat=True)

    form = BulkPasswordChangeForm(admin_ids)
    context = {
        'title': 'Change Password',
        'form': form,
        'id': 'frm_bulk_password',
        'form_action': request.path,
        'status': 'display'
    }

    return render(request, template, context)


def do_person_bulk_action(request):
    """Bulk actions for the Distinct Administrators tab.

    Rows there are HSAdministrator records, so `ids[]` are administrator ids —
    unlike do_bulk_action, whose ids are HSAdministratorPosition rows.
    """
    action = request.GET.get('action')
    ids = request.GET.getlist('ids[]')

    if request.method == 'POST':
        action = request.POST.get('action')
        ids = request.POST.getlist('ids[]') or ids

    valid_ids = []
    for record_id in ids:
        try:
            uuid.UUID(str(record_id))
        except (ValueError, AttributeError, TypeError):
            continue
        valid_ids.append(record_id)

    if action == 'password_reset_link':
        admins = HSAdministrator.objects.filter(
            id__in=valid_ids).select_related('user')
        return render_reset_links(request, admins)

    if action == 'change_password':
        return manage_change_password(request, admin_ids=valid_ids)

    if action == 'delete':
        if request.method != 'POST':
            return JsonResponse({
                'status': 'error',
                'message': 'Delete requires POST.',
            }, status=405)

        deleted = skipped = 0
        for record_id in valid_ids:
            try:
                record = HSAdministrator.objects.get(pk=record_id)
            except HSAdministrator.DoesNotExist:
                skipped += 1
                continue
            try:
                HSAdministratorNote.objects.filter(hsadmin=record).delete()
                HSAdministrator.delete_record(record)
                deleted += 1
            except Exception:
                # Roles reference the administrator with on_delete=PROTECT.
                # Report the skip; deleting their roles is a separate decision.
                skipped += 1

        return JsonResponse({
            'status': 'success',
            'message': (
                f'{deleted} deleted, {skipped} skipped '
                '(skipped administrators still hold roles).'
            ),
        })

    return JsonResponse({
        'status': 'error',
        'message': 'Unknown action.',
    }, status=400)
