from django.db.models import Q
from django.views import View
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt


from django.db.models import Count 
from cis.models.highschool_administrator import (
    HSPosition, HSAdministratorPosition
)
from cis.forms.highschool import HSPositionForm, MigrateHSPositionForm

from cis.menu import cis_menu, draw_menu
from cis.services.table_configs import get_table_config
build_hs_roles_table_config = get_table_config('hs_roles_table').build_config

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..serializers.highschool_admin import HSPositionSerializer
from cis.utils import CIS_user_only

class HSPositionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HSPositionSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        return HSPosition.objects.annotate(hsadministratorposition_count=Count('hsadministratorposition')).all()


def delete_record(request, record_id):
    record = get_object_or_404(HSPosition, pk=record_id)

    try:
        record.delete()
    except Exception as e:
        return JsonResponse({
            'message': 'Unable to delete record' + str(e),
            'status': 'error'
        }, status=400)
    return JsonResponse({
        'message': 'Successfully deleted record',
        'status': 'success'
    })

@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/hs_admin/role.html'    
    record = get_object_or_404(HSPosition, pk=record_id)
    
    migration_form = MigrateHSPositionForm(record=record)
    form = HSPositionForm(instance=record)

    if request.method == 'POST':

        if request.POST.get('action') == 'migrate_position':
            migration_form = MigrateHSPositionForm(
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
        else:
            form = HSPositionForm(request.POST, instance=record)

            if form.is_valid():
                record = form.save(commit=False)
                record.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:hs_role', record_id=record_id)
    
    administrators = HSAdministratorPosition.objects.filter(position=record.id)
    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'highschools', 'hs_roles'),
            'record': record,
            'migration_form': migration_form,
            'administrators': administrators
        })

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/hs_admin/role-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = HSPositionForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            record = form.save(commit=False)
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
            return redirect('cis:hs_role', record_id=record.id) #d
        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = HSPositionForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'highschools', 'hs_roles')
        })

def index(request):
    '''
    HS Role search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'highschools', 'school_roles')

    template = 'cis/hs_admin/roles.html'

    index_table = build_hs_roles_table_config(
        variant='hs_roles_index',
        api_url='/ce/api/hs-position?format=datatables',
        details_prefix='/ce/highschool_role/',
    )

    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'High School Admin. Roles',
            'api_url': '/ce/api/hs-position?format=datatables',
            'index_table': index_table,
            'urls': {
                'details_prefix': '/ce/highschool_role/',
                'add_new': 'cis:hs_role_add_new'
            }
        }
    )