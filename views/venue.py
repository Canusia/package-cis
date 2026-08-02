# Venue Views

from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse

from django.conf import settings
from cis.models.event import Venue
from cis.forms.venue import VenueForm

from cis.menu import cis_menu, draw_menu

def index(request):
    '''
    Venue search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'events', 'venues')

    template = 'cis/venue/index.html'
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
        record_list = Venue.objects.all().order_by(
            order_by if order == 'asc' else f"-{order_by}")
    else:
        qry = Q()
        qry.add(Q(name__icontains=query), Q.OR)

        record_list = Venue.objects.filter(qry).order_by(
            order_by if order == 'asc' else f"-{order_by}")

    if request.GET.get('export') == 'excel':
        return Venue.export_to_excel(record_list)

    search_help = """
        <ul class='ml-0 pl-3'>
        <li class=''>Venue Name</li>
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
    template = 'cis/venue/add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = VenueForm(request.POST)
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
            return redirect('cis:venue', record_id=record.id) #d
        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ' '.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = VenueForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'events', 'venues')
        })

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/venue/detail.html'
    record = get_object_or_404(Venue, pk=record_id)

    if request.method == 'POST':
        form = VenueForm(request.POST, instance=record)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success') 
            return redirect('cis:venue', record_id=record_id)
    else:
        form = VenueForm(instance=record)

    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'events', 'venues'),
            'record': record
        })
