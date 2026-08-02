from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from cis.forms.course import TechCenterForm

from cis.menu import cis_menu, draw_menu

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..models.course import TechCenter
from ..serializers.course import TechCenterSerializer

from cis.utils import CIS_user_only

class TechCenterViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CIS_user_only]
    serializer_class = TechCenterSerializer

    def get_queryset(self):
        return TechCenter.objects.all().order_by('name')

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/course/tech_center.html'
    record = get_object_or_404(TechCenter, pk=record_id)

    if request.method == 'POST':
        form = TechCenterForm(request.POST, instance=record)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success')
            return redirect('cis:tech_center', record_id=record_id)
    else:
        form = TechCenterForm(instance=record)

    return render(
        request,
        template, {
            'form': form,
            'page_title': "UMA Center",
            'labels': {
                'all_items': 'All'
            },
            'urls': {
                'add_new': 'cis:tech_center_add_new',
                'all_items': 'cis:tech_centers'
            },
            'menu': draw_menu(cis_menu, 'campus', 'tech_center'),
            'record': record
        })

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/course/tech_center-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = TechCenterForm(request.POST)
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
            return redirect('cis:tech_center', record_id=record.id) #d
        
        if ajax == '1':
            data = {
                'status':'error',
                'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
            }
            return JsonResponse(data)
    else:
        form = TechCenterForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New",
            'labels': {
                'all_items': 'All Centers'
            },
            'urls': {
                'add_new': 'cis:tech_center_add_new',
                'all_items': 'cis:tech_centers'
            },
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'campus', 'tech_center')
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'campus', 'tech_center')
    template = 'cis/course/tech_centers.html'

    return render(
        request,
        template, {
            'page_title': 'UMA Centers',
            'urls': {
                'add_new': 'cis:tech_center_add_new',
                'details_prefix': '/ce/tech_center/'
            },
            'menu': menu,
            'api_url': '/ce/api/tech_center?format=datatables'
        }
    )
