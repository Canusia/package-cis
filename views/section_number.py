from django.db.models import Q
from django.contrib import messages
from django.conf import settings
from django.db import IntegrityError

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse

from cis.models.section import (
    SectionNumber, ClassSection
)
from cis.forms.section import SectionNumberForm
from cis.menu import cis_menu, draw_menu


def delete_record(request, record_id):
    record = get_object_or_404(SectionNumber, pk=record_id)
    try:
        record.delete()
    except IntegrityError:
        messages.add_message(
            request,
            messages.SUCCESS,
            'Successfully deleted record',
            'list-group-item-success')
        return redirect("cis:section_number", record.id)

    messages.add_message(
        request,
        messages.SUCCESS,
        'Successfully deleted record',
        'list-group-item-success')
    return redirect("cis:section_numbers")

def index(request):
    '''
    Section Number search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'classes', 'section_numbers')

    template = 'cis/section_numbers/index.html'
    query = request.GET.get('q', '')
    page = request.GET.get('page', 1)
    order_by = request.GET.get('order_by', 'name').lower()
    order = request.GET.get('order', 'asc')

    valid_order_by_fields = [
        'name', 'number',
    ]
    if order_by not in valid_order_by_fields:
        order_by = 'name'

    valid_order = [
        'asc', 'desc'
    ]
    if order not in valid_order:
        order = 'asc'

    if not query:
        record_list = SectionNumber.objects.all().order_by(
            order_by if order == 'asc' else f"-{order_by}")
    else:
        qry = Q()
        qry.add(Q(name__icontains=query), Q.OR)
        qry.add(Q(number__icontains=query), Q.OR)

        # try:
            # query = int(query)
            # qry.add(Q(temp_id=query), Q.OR)
        # except ValueError:
            # pass

        record_list = SectionNumber.objects.filter(
            qry).order_by(order_by if order == 'asc' else f"-{order_by}")

    search_help = """
        <ul class='ml-0 pl-3'>
        <li class=''>Name</li>
        <li class=''>Number</li>
        </ul>
        """

    if request.GET.get('export') == 'excel':
        return HighSchool.export_to_excel(record_list)

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
    records = HighSchool.objects.filter(
        name__contains=search
    )

    result = {'items':[]}
    if records:
        for r in records:
            r = {
                'html_url': reverse('cis:hs_detail', kwargs={'record_id':r.id}),
                'name': r.name
            }
            result['items'].append(r)

    return JsonResponse(result)

def add_new(request):
    '''
    Add new
    '''
    template = 'cis/section_numbers/add-new.html'
    if request.method == 'POST':
        form = SectionNumberForm(request.POST)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully added record',
                'list-group-item-success') 
            return redirect('cis:section_number', record_id=record.id) #d
    else:
        form = SectionNumberForm()

    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'classes', 'section_numbers')
        })

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Details page
    '''
    template = 'cis/section_numbers/details.html'
    record = get_object_or_404(SectionNumber, pk=record_id)

    if request.method == 'POST':
        form = SectionNumberForm(request.POST, instance=record)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success') 
            return redirect('cis:section_number', record_id=record_id)
    else:
        form = SectionNumberForm(instance=record)

    notes = [] #HighSchoolNote.objects.filter(highschool=record)
    sections = ClassSection.objects.filter(section_number=record).order_by("term")

    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'classes', 'section_numbers'),
            'record': record,
            # 'instructors': instructors,
            # 'administrators': administrators,
            # 'future_courses': future_courses,
            'sections': sections,
            # 'notes': notes
        })
