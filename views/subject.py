from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse

from cis.models.course import (
    Subject, Course, Department
)
from cis.forms.course import SubjectForm

from cis.menu import cis_menu, draw_menu


from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..serializers.course import CohortSerializer
from cis.utils import CIS_user_only

class CohortViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CohortSerializer

    def get_queryset(self):
        return Subject.objects.all()

from django.views.decorators.clickjacking import xframe_options_exempt

def delete_record(request, record_id):
    record = get_object_or_404(Subject, pk=record_id)

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

@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/course/subject.html'    
    record = get_object_or_404(Subject, pk=record_id)

    if request.method == 'POST':
        form = SubjectForm(request.POST, instance=record)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success') 
            return redirect('cis:subject', record_id=record_id)
    else:
        form = SubjectForm(instance=record)

    courses = Course.objects.filter(subject=record.id)
    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New",
            'labels': {
                'all_items': 'All Subjects'
            },
            'urls': {
                'add_new': 'cis:subject_add_new',
                'all_items': 'cis:subjects'
            },
            'menu': draw_menu(cis_menu, 'classes', 'subjects'),
            'record': record,
            'courses': courses
        })

def add_new(request):
    '''
    Add new page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/course/subject-add_new.html'
    ajax = request.GET.get('ajax', None)

    if request.method == 'POST':
        form = SubjectForm(request.POST)
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
            return redirect('cis:subject', record_id=record.id) #d
        
        if ajax == '1':
            data = {
                'status':'error',
                'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
            }
            return JsonResponse(data)
    else:
        form = SubjectForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New Subject",
            'labels': {
                'all_items': 'All Subjects'
            },
            'urls': {
                'add_new': 'cis:subject_add_new',
                'all_items': 'cis:subjects'
            },
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'classes', 'subjects')
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'classes', 'subjects')

    template = 'cis/course/subject-list.html'
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
        record_list = Subject.objects.all().order_by(order_by if order == 'asc' else f"-{order_by}")
    else:
        record_list = Subject.objects.filter(
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
            'page_title': 'Subjects',
            'urls': {
                'add_new': 'cis:subject_add_new',
                'details': 'cis:subject'
            },
            'menu': menu,
            'records':records,
            'q': query,
            'order_by': order_by,
            'order': order})
