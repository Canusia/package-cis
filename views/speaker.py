from django.db import IntegrityError
from django.db.models import Q
from django.conf import settings

from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from datetime import datetime

from cis.models.customuser import CustomUser
from cis.models.event import Speaker
from cis.forms.speaker import SpeakerForm

from cis.menu import cis_menu, draw_menu

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/speakers/detail.html'    
    record = get_object_or_404(Speaker, pk=record_id)
    
    if request.method == 'POST':
        form = SpeakerForm(request.POST)

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
                return redirect('cis:speaker', record_id=record_id)
            except IntegrityError:
                form._errors['email'] = ['An account with this email already exists.']
    else:
        form = SpeakerForm(initial={
            'first_name':record.user.first_name,
            'last_name':record.user.last_name,
            'email':record.user.email
        })

    notes = []
    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'events', 'speakers'),
            'record': record,
            'notes': notes
        })

def add_new(request):
    '''
    Add new page
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/speakers/add_new.html'

    if request.method == 'POST':
        form = SpeakerForm(request.POST)
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

                record = Speaker(user=user)
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
                return redirect('cis:speaker', record_id=record.id) #d
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
        form = SpeakerForm()

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'events', 'speakers')
        })

def index(request):
    '''
    Speaker search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'events', 'speakers')

    template = 'cis/speakers/index.html'
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
        record_list = Speaker.objects.all().order_by('user__first_name')
    else:
        record_list = Speaker.objects.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(user__email__icontains=query))

    if request.GET.get('export') == 'excel':
        return Speaker.export_to_excel(record_list)

    search_help = """
        <ul class='ml-0 pl-3'>
        <li class=''>First Name</li>
        <li class=''>Last Name</li>
        <li class=''>Email</li>
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
        template, {
            'menu': menu,
            'count': paginator.count,
            'search_help': search_help,
            'records':records,
            'q': query,
            'order_by': order_by,
            'order': order})
