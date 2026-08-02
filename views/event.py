from django.db.models import Q
from django.contrib import messages
from django.conf import settings

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse
from django.db import IntegrityError

from django.template.context_processors import csrf
from crispy_forms.utils import render_crispy_form

from cis.models.event import (
    Event, Speaker, EventSpeaker,
    EventCohort, EventAttendee, EventItem
)

from cis.forms.event import (
    EventForm, EventSpeakerForm,
    EventCohortForm, EventRefreshmentForm,
    EventCopyReqForm, EventCISExpenseForm,
    EventCohortExpenseForm
)

from cis.menu import cis_menu, draw_menu

def index(request):
    '''
    Event and index page for staff
    '''
    menu = draw_menu(cis_menu, 'events', 'events')

    template = 'cis/events/index.html'
    query = request.GET.get('q', '')
    page = request.GET.get('page', 1)
    order_by = request.GET.get('order_by', 'name').lower()
    order = request.GET.get('order', 'asc')

    valid_order_by_fields = [
        'name', 'start_time', 'end_time'
    ]
    if order_by not in valid_order_by_fields:
        order_by = 'name'

    valid_order = [
        'asc', 'desc'
    ]
    if order not in valid_order:
        order = 'asc'

    if not query:
        record_list = Event.objects.all().order_by(
            order_by if order == 'asc' else f"-{order_by}")
    else:
        qry = Q()
        qry.add(Q(name__icontains=query), Q.OR)

        try:
            query = int(query)
            qry.add(Q(temp_id=query), Q.OR)
        except ValueError:
            pass

        record_list = Event.objects.filter(
            qry).order_by(order_by if order == 'asc' else f"-{order_by}")


    search_help = """
        <ul class='ml-0 pl-3'>
        <li class=''>Event Name</li>
        </ul>
        """
    
    if request.GET.get('export') == 'excel':
        return Event.export_to_excel(record_list)

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
    Add new record page
    '''
    base_template = 'cis/logged-base.html'
    template = 'cis/events/add_new.html'
    if request.method == 'POST':
        form = EventForm(request.POST)

        if form.is_valid():
            record = form.save(commit=False)
            record.created_by = request.user
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully added record',
                'list-group-item-success')
            return redirect('cis:event', record_id=record.id) #d
    else:
        form = EventForm()

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Add New Event",
            'base_template': base_template,
            'labels': {
                'all_items': 'All Events'
            },
            'urls': {
                'add_new': 'cis:event_add_new',
                'all_items': 'cis:events'
            },
            'menu': draw_menu(cis_menu, 'events', 'events')
        })

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/events/details.html'
    record = get_object_or_404(Event, pk=record_id)

    if request.method == 'POST':
        form = EventForm(request.POST, instance=record)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated record',
                'list-group-item-success')
            return redirect('cis:event', record_id=record_id)
    else:
        form = EventForm(
            instance=record)

    notes = []
    speakers = EventSpeaker.objects.filter(event__id=record.id)
    cohorts = EventCohort.objects.filter(event__id=record.id)
    guest_list = EventAttendee.objects.filter(event__id=record.id)

    refreshment_form = EventRefreshmentForm(initial=record.get_item_info('refreshment'))
    copy_req_form = EventCopyReqForm(initial=record.get_item_info('copies'))

    cis_expense_form = EventCISExpenseForm(initial=record.get_item_info('cis expense'))
    cohort_expense_form = EventCohortExpenseForm(initial=record.get_item_info('cohort expense'))

    return render(
        request,
        template, {
            'form': form,
            'menu': draw_menu(cis_menu, 'events', 'events'),
            'page_title': "Event",
            'labels': {
                'all_items': 'All Events'
            },
            'urls': {
                'add_new': 'cis:event_add_new',
                'all_items': 'cis:events'
            },
            'record': record,
            'notes': notes,
            'speakers': speakers,
            'refreshmentForm': refreshment_form,
            'copyReqForm': copy_req_form,
            'cisExpenseForm': cis_expense_form,
            'cohortExpenseForm': cohort_expense_form,
            'cohorts': cohorts,
            'guest_list': guest_list
        })

def add_new_speaker(request):
    '''
    Add new speaker
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/events/manage_speaker.html'

    if request.method == 'POST':
        form = EventSpeakerForm(request.POST)

        if form.is_valid():
            try:
                if form.cleaned_data['id'] != '-1':
                    record = EventSpeaker.objects.get(pk=form.cleaned_data['id'])
                    record.speaker = form.cleaned_data['speaker']

                    record.save()
                else:
                    record = EventSpeaker()
                    record.speaker = form.cleaned_data['speaker']
                    record.created_by = request.user

                    event = Event.objects.get(pk=form.cleaned_data['event'])
                    record.event = event

                    record.save()

                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'success',
                        'message':'Successfully saved record',
                        'new_record_id':record.id,
                        'new_record_name':record.speaker.user.first_name,
                        'action': 'reload'
                    }
                    return JsonResponse(data)

            except IntegrityError as exception:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Looks like a duplicate entry'
                    }
                    return JsonResponse(data)
                form._errors['speaker'] = ['This speaker is already assigned to the event']

            except EventSpeaker.DoesNotExist:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Invalid ID received'
                    }
                    return JsonResponse(data)
                form._errors['highschool'] = ['An invalid ID was received']
    else:
        initial = {
            'event':request.GET.get('parent'),
            'id': '-1',
            'ajax': ajax
        }

        if request.GET.get('id', '-1') != '-1':
            record = EventSpeaker.objects.get(pk=request.GET.get('id'))
            initial['id'] = record.id
            initial['speaker'] = record.speaker

        form = EventSpeakerForm(initial=initial)
        event = Event.objects.get(pk=initial['event'])

    return render(
        request,
        template, {
            'form': form,
            'event': event,
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'events', 'events')
        })

def add_new_cohort(request):
    '''
    Add new cohort
    '''
    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/events/manage_cohort.html'

    if request.method == 'POST':
        form = EventCohortForm(request.POST)

        if form.is_valid():
            try:
                if form.cleaned_data['id'] != '-1':
                    record = EventCohort.objects.get(pk=form.cleaned_data['id'])
                    record.cohort = form.cleaned_data['cohort']

                    record.save()
                else:
                    record = EventCohort()
                    record.cohort = form.cleaned_data['cohort']
                    record.created_by = request.user

                    event = Event.objects.get(pk=form.cleaned_data['event'])
                    record.event = event

                    record.save()
                    EventAttendee.add_cohort_instructors_to_guest_list(event, record.cohort)

                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'success',
                        'message':'Successfully saved record',
                        'new_record_id':record.id,
                        'new_record_name':record.cohort.name,
                        'action': 'reload'
                    }
                    return JsonResponse(data)

            except IntegrityError as exception:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Looks like a duplicate entry'
                    }
                    return JsonResponse(data)
                form._errors['speaker'] = ['This cohort is already assigned to the event']

            except EventSpeaker.DoesNotExist:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Invalid ID received'
                    }
                    return JsonResponse(data)
                form._errors['highschool'] = ['An invalid ID was received']
    else:
        initial = {
            'event':request.GET.get('parent'),
            'id': '-1',
            'ajax': ajax
        }

        if request.GET.get('id', '-1') != '-1':
            record = EventCohort.objects.get(pk=request.GET.get('id'))
            initial['id'] = record.id
            initial['cohort'] = record.cohort

        form = EventCohortForm(initial=initial)
        event = Event.objects.get(pk=initial['event'])

    return render(
        request,
        template, {
            'form': form,
            'event': event,
            'ajax': ajax,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'events', 'events')
        })

def edit_event_item(request):
    item_type = request.GET.get('item_type')
    if item_type == 'refreshment':
        form = EventRefreshmentForm(request.GET)
    elif item_type == 'copies':
        form = EventCopyReqForm(request.GET)
    elif item_type == 'cis expense':
        form = EventCISExpenseForm(request.GET)
    else:
        form = EventCohortExpenseForm(request.GET)

    response = {}
    if form.is_valid():
        item = EventItem.save_item(item_type, form)

        initial = item.item
        initial['event'] = item.event.id
        initial['id'] = item.id

        form = form.__class__(initial=initial)
        response = {'status':'SUCCESS', 'message': 'Successfully saved record'}
    else:
        response = {
            'status':'ERROR',
            'message': 'There was an error completing your request. Please see below for additional information'}

    ctx = {}
    ctx.update(csrf(request))
    form_html = render_crispy_form(form, context=ctx)
    response['form_html'] = form_html
    return JsonResponse(response)

def delete_record_from_event(request):

    record_type = request.GET.get('record_type')
    record_id = request.GET.get('id')

    if record_type == 'cohort':
        event_cohort = EventCohort.objects.get(pk=record_id)
        event_cohort.delete()

    if record_type == 'speaker':
        event_speaker = EventSpeaker.objects.get(pk=record_id)
        event_speaker.delete()

    if record_type == 'guest':
        guests = request.GET.getlist('guest[]')
        if not guests:
            return JsonResponse({
                'status': 'ERROR',
                'message': 'Please select a record and try again.'})

        if request.GET.get('action') in ['mark_as_required', 'mark_as_optional']:
            participation = 'Required'
            if request.GET.get('action') == 'mark_as_optional':
                participation = "Optional"

            for guest in guests:
                event_guest = EventAttendee.objects.get(pk=guest)
                event_guest.participation = participation
                event_guest.save()

            return JsonResponse({
                'status': 'SUCCESS',
                'message': 'Successfully updated %d guest(s).' % len(guests)})
        else:
            for guest in guests:
                event_guest = EventAttendee.objects.get(pk=guest)
                event_guest.delete()

            return JsonResponse({
                'status': 'SUCCESS',
                'message': 'Successfully removed %d guest(s).' % len(guests)})

    return JsonResponse({'status':'SUCCESS'})