"""
Student Views
"""
import csv
import io

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse, HttpResponse

from django_login_history.models import Login

from cis.menu import draw_menu, cis_menu
from cis.models.customuser import CustomUser

from cis.forms.user import UserForm

def get_password_reset_link(request):
    record_id = request.GET.get('id')
    record = get_object_or_404(CustomUser, pk=record_id)

    url = record.get_password_reset_link()

    return JsonResponse({
        'url': url})

def add_new(request):
    '''
    Add new page
    '''

    if not request.user.can_edit_users:
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger') 
        return redirect('cis:dashboard')

    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html'
    template = 'cis/users/add_new.html'

    if request.method == 'POST':
        form = UserForm(request.POST)
        
        if form.is_valid():
            try:
                user = CustomUser.add_new_staff(form)

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully saved record',
                    'list-group-item-success')
                return redirect('cis:user', record_id=user.id) #d
            except IntegrityError as intError:
                form._errors['email'] = ['Sorry, there was an error while adding user']
                print(intError)
        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = UserForm()

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax, 
            'page_title': "Add New",
            'labels': {
                'all_items': 'All Users'
            },
            'urls': {
                'add_new': 'cis:user_add_new',
                'all_items': 'cis:users'
            },
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'users', 'users')
        })

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    """
    Record details page
    """

    if not request.user.can_edit_users:
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger') 
        return redirect('cis:dashboard')

    template = 'cis/users/detail.html'
    record = get_object_or_404(CustomUser, pk=record_id)

    if request.method == 'POST':
        form = UserForm(request.POST)

        if form.is_valid():
            record.update(form)

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success') 
            return redirect('cis:user', record_id=record_id)
    else:
        campus = {}
        if record.campus:
            campus = record.campus

        form = UserForm(initial={
            'first_name':record.first_name,
            'last_name':record.last_name,
            'email':record.email,
            'username':record.username,
            'is_active':'Yes' if record.is_active else 'No',
            'process_campus': campus.get('process_campus', ''),
            'manage_settings': campus.get('manage_settings'),
            'manage_staff_accounts': campus.get('manage_staff_accounts'),
            'default_campus': campus.get('default_campus', ''),
        })

    return render(
        request,
        template, {
            'form': form,
            'page_title': "User",
            'history': Login.objects.filter(user=record).order_by('-date'),
            'labels': {
                'all_items': 'All Users'
            },
            'urls': {
                'add_new': 'cis:user_add_new',
                'all_items': 'cis:users'
            },
            'menu': draw_menu(cis_menu, 'users', 'users'),
            'record': record,
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'users', 'users')

    if not request.user.can_edit_users:
        messages.add_message(
            request,
            messages.SUCCESS,
            'You do not have permission to edit this',
            'list-group-item-danger') 
        return redirect('cis:dashboard')

    template = 'cis/users/index.html'
    query = request.GET.get('q', '')
    page = request.GET.get('page', 1)
    order_by = request.GET.get('order_by', 'created_at').lower()
    order = request.GET.get('order', 'desc')

    valid_order_by_fields = [
        'first_name',
        'created_at',
    ]
    if order_by not in valid_order_by_fields:
        order_by = 'created_at'

    valid_order = [
        'asc', 'desc'
    ]
    if order not in valid_order:
        order = 'desc'

    record_list = CustomUser.objects.filter(groups__name='ce').order_by(
        order_by if order == 'asc' else f"-{order_by}")
    
    if query:
        record_list = record_list.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(psid=query)
            ).order_by(order_by if order == 'asc' else f"-{order_by}")

    if(request.GET.get('export') == 'excel'):
        return CustomUser.export_to_excel(record_list)

    search_help = """
        <ul class='ml-0 pl-3'>
        <li class=''>First Name</li>
        <li class=''>Last Name</li>
        </ul>
        """

    paginator = Paginator(record_list, settings.MY_CE.get('paginator_per_page', 30))
    try:
        records = paginator.page(page)
    except PageNotAnInteger:
        records = paginator.page(1)
    except EmptyPage:
        records = paginator.page(paginator.num_pages)

    return render(
        request,
        template,
        {
            'page_title': 'Users',
            'search_help': search_help,
            'urls': {
                'add_new': 'cis:user_add_new',
                'details': 'cis:user'
            },
            'count': paginator.count,
            'menu': menu,
            'records':records,
            'q': query,
            'order_by': order_by,
            'order': order})
