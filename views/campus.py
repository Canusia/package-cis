from django.db.models import Q
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.views.decorators.clickjacking import xframe_options_exempt

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cis.models.course import (
    Campus
)
from ..models.term import Term

from cis.forms.course import CampusForm

from cis.menu import cis_menu, draw_menu

from ..serializers.course import CampusSerializer
from cis.utils import CIS_user_only, active_term

class CampusViewSet(viewsets.ReadOnlyModelViewSet):
    # PT-44: /ce/api/campus/ backs the CIS-only /ce/campuses/ page.
    # Without this, the viewset inherits DRF's default IsAuthenticated and
    # leaks campus records to any authenticated role (e.g. highschool_admin).
    permission_classes = [CIS_user_only]
    serializer_class = CampusSerializer

    def get_queryset(self):
        code = self.request.GET.get('code', getattr(settings, 'CAMPUS_CODE_PREFIX'))

        records = Campus.objects.all()
        if code:
            records = records.filter()
        return records

@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/course/campus.html'
    record = get_object_or_404(Campus, pk=record_id)

    if request.method == 'POST':
        form = CampusForm(request.POST, instance=record)

        if form.is_valid():
            record = form.save(commit=False)
            record.locations.clear()
            if form.cleaned_data['locations']:
                for location in form.cleaned_data['locations']:
                    record.locations.add(location)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success')
            return redirect('cis:campus', record_id=record_id)
    else:
        form = CampusForm(instance=record)

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Campus",
            'labels': {
                'all_items': 'All Campus'
            },
            'urls': {
                'add_new': 'cis:campus_add_new',
                'all_items': 'cis:campuses'
            },
            'highschools_served_api_url': f'/ce/api/highschool-served/?format=datatables&campus_id={record.id}',
            'classes_registered_api_url': f'/ce/api/class-registered/?format=datatables&campus_id={record.id}',
            'terms': Term.objects.all().order_by('-code'),
            'active_term': active_term(),
            'menu': draw_menu(cis_menu, 'campus', 'campuses'),
            'record': record
        })

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/course/campus-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = CampusForm(request.POST)
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
            return redirect('cis:campus', record_id=record.id) #d
        
        if ajax == '1':
            data = {
                'status':'error',
                'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
            }
            return JsonResponse(data)
    else:
        form = CampusForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New Campus",
            'labels': {
                'all_items': 'All Campus'
            },
            'urls': {
                'add_new': 'cis:campus_add_new',
                'all_items': 'cis:campuses'
            },
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'campus', 'campuses')
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'campus', 'campuses')
    template = 'cis/course/campus-list.html'

    return render(
        request,
        template, {
            'page_title': 'Campus',
            'urls': {
                'add_new': 'cis:campus_add_new',
                'details_prefix': '/ce/campus/'
            },
            'menu': menu,
            'api_url': '/ce/api/campus?format=datatables'
        }
    )    

