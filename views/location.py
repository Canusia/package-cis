from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from cis.forms.course import LocationForm
from cis.models.course import Campus, Location

from cis.menu import cis_menu, draw_menu

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..serializers.course import LocationSerializer, Location
from cis.utils import CIS_user_only

class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CIS_user_only]
    serializer_class = LocationSerializer

    def get_queryset(self):
        campus_id = self.request.GET.get('campus', None)

        records = Location.objects.all().order_by('name')
        if campus_id:
            campus = Campus.objects.get(pk=campus_id)
            records = records.filter(
                pk__in=campus.locations.all()
            )
        return records

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/course/location.html'
    record = get_object_or_404(Location, pk=record_id)

    if request.method == 'POST':
        form = LocationForm(request.POST, instance=record)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success')
            return redirect('cis:location', record_id=record_id)
    else:
        form = LocationForm(instance=record)

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Location",
            'labels': {
                'all_items': 'All Locations'
            },
            'urls': {
                'add_new': 'cis:location_add_new',
                'all_items': 'cis:locations'
            },
            'menu': draw_menu(cis_menu, 'campus', 'locations'),
            'record': record
        })

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/course/location-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = LocationForm(request.POST)
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
            return redirect('cis:location', record_id=record.id) #d
        
        if ajax == '1':
            data = {
                'status':'error',
                'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
            }
            return JsonResponse(data)
    else:
        form = LocationForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New",
            'labels': {
                'all_items': 'All Locations'
            },
            'urls': {
                'add_new': 'cis:location_add_new',
                'all_items': 'cis:locations'
            },
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'campus', 'locations')
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'campus', 'locations')
    template = 'cis/course/locations.html'

    return render(
        request,
        template, {
            'page_title': 'Location',
            'urls': {
                'add_new': 'cis:location_add_new',
                'details_prefix': '/ce/location/'
            },
            'menu': menu,
            'api_url': '/ce/api/location?format=datatables'
        }
    )
