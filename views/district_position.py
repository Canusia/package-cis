from django.db.models import Q
from django.views import View
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse

from cis.models.district import (
    DistrictPosition, DistrictAdministratorPosition
)
from cis.forms.district import DistrictPositionForm

from cis.menu import cis_menu, draw_menu


from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/district_role.html'    
    record = get_object_or_404(DistrictPosition, pk=record_id)
    
    if request.method == 'POST':
        form = DistrictPositionForm(request.POST, instance=record)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success') 
            return redirect('cis:district_role_detail', record_id=record_id)
    else:
        form = DistrictPositionForm(instance=record)

    administrators = DistrictAdministratorPosition.objects.filter(position=record.id)
    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'highschools', 'district_roles'),
            'record': record,
            'administrators': administrators
        })

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/district_role-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = DistrictPositionForm(request.POST)
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
            return redirect('cis:district_role_detail', record_id=record.id) #d
        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ' '.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = DistrictPositionForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'highschools', 'district_roles')
        })

def index(request):
    '''
    District Role search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'highschools', 'district_roles')

    template = 'cis/district_roles.html'
    query = request.GET.get('q', '')
    page = request.GET.get('page', 1)
    order_by = request.GET.get('order_by', 'name').lower()
    order = request.GET.get('order', 'asc')

    valid_order_by_fields = [
        'name'
    ]
    if order_by not in valid_order_by_fields:
        order_by = 'name'

    valid_order = [
        'asc', 'desc'
    ]
    if order not in valid_order:
        order = 'asc'

    if not query:
        record_list = DistrictPosition.objects.all().order_by(order_by if order == 'asc' else f"-{order_by}")
    else:
        record_list = DistrictPosition.objects.filter(
            Q(name__contains=query)).order_by(order_by if order == 'asc' else f"-{order_by}")

    paginator = Paginator(record_list, 10)
    try:
        records = paginator.page(page)
    except PageNotAnInteger:
        records = paginator.page(1)
    except EmptyPage:
        records = paginator.page(paginator.num_pages)

    return render(
        request,
        template, {
            'menu': menu,
            'records':records,
            'q': query,
            'order_by': order_by,
            'order': order})
