from django.db.models import Q, Count
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse

from rest_framework import viewsets

from cis.models.highschool import HighSchool
from cis.models.district import District, DistrictAdministratorPosition
from cis.forms.district import DistrictForm, MigrateForm

from cis.menu import cis_menu, draw_menu
from cis.utils import CIS_user_only
from cis.serializers.highschool import DistrictListSerializer
from cis.services.table_configs import get_table_config
build_districts_table_config = get_table_config('districts_table').build_config


class DistrictViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DistrictListSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        return District.objects.annotate(num_highschools=Count('highschool'))


def delete_record(request, record_id):
    record = get_object_or_404(District, pk=record_id)

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

def index(request):
    '''
    District search and index page for staff (AJAX-backed).
    '''
    menu = draw_menu(cis_menu, 'highschools', 'all_districts')
    template = 'cis/districts.html'
    return render(
        request,
        template, {
            'menu': menu,
            'districts_table': build_districts_table_config(
                variant='districts_index',
                api_url='/ce/api/district/?format=datatables',
                details_prefix='/ce/district/',
            ),
        }
    )

def ajax_search(request):
    search = request.GET.get('q','')
    records = District.objects.filter(
        name__contains=search
    )

    result = {'items':[]}
    if records:
        for r in records:
            r = {
                'html_url': reverse('cis:district_detail', kwargs={'record_id':r.id}),
                'name': r.name
            }
            result['items'].append(r)

    return JsonResponse(result)

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/district-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = DistrictForm(request.POST)
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
            return redirect('cis:district_detail', record_id=record.id) #d
        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ' '.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = DistrictForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'highschools', 'all_districts')
        })

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/district.html'    
    record = get_object_or_404(District, pk=record_id)
    
    highschools = HighSchool.objects.filter(district_id=record_id)
    administrators = DistrictAdministratorPosition.objects.filter(district_id=record_id)

    form = DistrictForm(instance=record)
    migration_form = MigrateForm(record=record)

    if request.method == 'POST':

        if request.POST.get('action') == 'migrate_district':
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
        else:
            form = DistrictForm(request.POST, instance=record)

            if form.is_valid():
                record = form.save(commit=False)
                record.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:district_detail', record_id=record_id)
    
    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'highschools', 'all_districts'),
            'record': record,
            'highschools': highschools,
            'administrators': administrators,
            'migration_form': migration_form
        })
