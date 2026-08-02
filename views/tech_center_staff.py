from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from cis.forms.course import TechCenterStaffForm
from ..models.tech_center_staff import TechCenterStaff

from cis.menu import cis_menu, draw_menu

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..serializers.course import TechCenterStaffSerializer
from cis.utils import CIS_user_only, TECHSTAFF_user_only

class TechCenterStaffViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CIS_user_only | TECHSTAFF_user_only]
    serializer_class = TechCenterStaffSerializer

    def get_queryset(self):
        return TechCenterStaff.objects.all().order_by('user__first_name')

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/course/tech_center_staff.html'
    record = get_object_or_404(TechCenterStaff, pk=record_id)

    if request.method == 'POST':
        form = TechCenterStaffForm(request.POST)

        if form.is_valid():
            record = form.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success')
            return redirect('cis:tech_center_staff', record_id=record_id)
    else:
        form = TechCenterStaffForm(initial={
            'id': record.id,
            'first_name': record.user.first_name,
            'last_name': record.user.last_name,
            'email': record.user.email,
            'username': record.user.username,
            'tech_center': record.tech_center
        })

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Tech. Center Staff",
            'labels': {
                'all_items': 'All Staff'
            },
            'urls': {
                'add_new': 'cis:tech_center_staff_add_new',
                'all_items': 'cis:tech_center_staffs'
            },
            'menu': draw_menu(cis_menu, 'campus', 'tech_center_staff'),
            'record': record
        })

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/course/tech_center_staff-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = TechCenterStaffForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            record = form.save()
            
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
            return redirect('cis:tech_center_staff', record_id=record.id) #d
        
        if ajax == '1':
            data = {
                'status':'error',
                'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
            }
            return JsonResponse(data)
    else:
        form = TechCenterStaffForm(initial={
            'id':'-1'
        })

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New",
            'labels': {
                'all_items': 'All Staff'
            },
            'urls': {
                'add_new': 'cis:tech_center_staff_add_new',
                'all_items': 'cis:tech_center_staffs'
            },
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'campus', 'locations')
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'campus', 'tech_center_staff')
    template = 'cis/course/tech_center_staffs.html'

    return render(
        request,
        template, {
            'page_title': 'Tech Center Staff',
            'urls': {
                'add_new': 'cis:tech_center_staff_add_new',
                'details_prefix': '/ce/tech_center_staff/'
            },
            'menu': menu,
            'api_url': '/ce/api/tech_center_staff?format=datatables'
        }
    )
