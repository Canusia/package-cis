from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from cis.models.customuser import CustomUser
from cis.models.district import (
    DistrictPosition, DistrictAdministrator, DistrictAdministratorPosition
)
from cis.forms.district import (
    DistrictAdministratorForm, DistrictAdministratorPositionForm
)

from cis.menu import cis_menu, draw_menu


from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/district_admin/detail.html'    
    record = get_object_or_404(DistrictAdministrator, pk=record_id)
    roles = DistrictAdministratorPosition.objects.filter(district_admin=record_id)
    
    if request.method == 'POST':
        form = DistrictAdministratorForm(request.POST)

        if form.is_valid():
            try:
                user = CustomUser.objects.get(pk=record.user.id)

                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.email = form.cleaned_data['email']

                user.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:district_admin_detail', record_id=record_id)
            except IntegrityError:
                form._errors['email'] = ['An account with this email already exists.']
    else:
        form = DistrictAdministratorForm(initial={
            'first_name':record.user.first_name,
            'last_name':record.user.last_name,
            'email':record.user.email
        })

    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'highschools', 'district_admin'),
            'record': record,
            'roles': roles
        })

def add_new_role(request):
    '''
    Add new role to district administrator
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/district_admin/manage_role.html'

    if request.method == 'POST':
        form = DistrictAdministratorPositionForm(request.POST)

        if form.is_valid():
            try:
                if form.cleaned_data['id'] != '-1':
                    record = DistrictAdministratorPosition.objects.get(pk=form.cleaned_data['id'])
                    record.district = form.cleaned_data['district']
                    record.status = form.cleaned_data['status']
                    record.position = form.cleaned_data['position']

                    record.save()
                else:
                    record = DistrictAdministratorPosition()
                    record.district = form.cleaned_data['district']
                    record.position = form.cleaned_data['position']
                    record.status = form.cleaned_data['status']
                    d_admin = DistrictAdministrator.objects.get(pk=form.cleaned_data['district_admin'])
                    record.district_admin = d_admin

                    record.save()

                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'success',
                        'message':'Successfully saved record',
                        'new_record_id':record.id,
                        'new_record_name':record.district_admin.user.first_name,
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
                form._errors['district'] = ['The role already exists for this district']

            except DistrictAdministratorPosition.DoesNotExist:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Invalid role ID received'
                    }
                    return JsonResponse(data)
                form._errors['district'] = ['An invalid ID was received']
    else:
        initial = {
            'district_admin':request.GET.get('parent'),
            'id': '-1',
            'ajax': ajax
        }

        if request.GET.get('id', '-1') != '-1':
            record = DistrictAdministratorPosition.objects.get(pk=request.GET.get('id'))
            initial['id'] = record.id
            initial['district'] = record.district.id
            initial['status'] = record.status
            initial['position'] = record.position.id

        form = DistrictAdministratorPositionForm(initial=initial)

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'highschools', 'district_admin')
        })

def add_new(request):
    '''
    Add new page
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/district_admin/add_new.html'

    if request.method == 'POST':
        form = DistrictAdministratorForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            try:
                user = CustomUser()
                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.email = form.cleaned_data['email']
                user.username = form.cleaned_data['email'].lower()
                
                #check if user email is already in the system
                if not CustomUser.objects.filter(email=form.cleaned_data['email']).exists():
                    user.save()
                else:
                    user = CustomUser.objects.get(email=form.cleaned_data['email'])
                    # check if a districtadmin account already exists for user

                record = DistrictAdministrator(user=user)
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
                return redirect('cis:district_admin_detail', record_id=record.id) #d
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
        form = DistrictAdministratorForm()

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'highschools', 'district_admin')
        })

def index(request):
    '''
    District Admin search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'highschools', 'district_admins')

    template = 'cis/district_admin/index.html'
    query = request.GET.get('q', '')
    page = request.GET.get('page', 1)
    order_by = request.GET.get('order_by', 'user_first_name').lower()
    order = request.GET.get('order', 'asc')

    valid_order_by_fields = [
        'user__email', 'user__first_name'
    ]
    if order_by not in valid_order_by_fields:
        order_by = 'user__email'

    valid_order = [
        'asc', 'desc'
    ]
    if order not in valid_order:
        order = 'asc'

    if not query:
        record_list = DistrictAdministrator.objects.all().order_by('user__first_name')
    else:
        record_list = DistrictAdministrator.objects.filter(
            Q(user__first_name__contains=query) |
            Q(user__last_name__contains=query) |
            Q(user__email__contains=query))

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
