"""
SIS Message Views
"""
import csv, io, logging

from django.conf import settings
from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.utils.safestring import mark_safe
from django.views.decorators.clickjacking import xframe_options_exempt

from cis.utils import (
    get_uploaded_file, active_term,
    registration_terms, is_student_registration_open
)
from cis.models.sis import SIS_Subscription, SIS_SubscriptionSerializer

logger = logging.getLogger(__name__)

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from rest_framework.decorators import api_view 
from rest_framework.response import Response

from cis.utils import CIS_user_only, FACULTY_user_only, INSTRUCTOR_user_only
from cis.menu import cis_menu, draw_menu

from ..serializers.note import StudentNoteSerializer

class SIS_SubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SIS_SubscriptionSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        records = SIS_Subscription.objects.all()

        return records
        
@xframe_options_exempt
def detail(request, record_id):
    """
    Record details page
    """
    template = 'cis/students/sis_message.html'
    record = get_object_or_404(SIS_Subscription, pk=record_id)

    if request.GET.get('process'):
        record.process()
        
    return render(
        request,
        template, {
            'page_title': "SIS Message",
            'record': record,
        })

def index(request):
    menu = draw_menu(cis_menu, 'students', 'sis_messages')
    template = 'cis/students/sis_messages.html'
    
    if request.GET.get('get_messages'):
        import importlib.util
        if importlib.util.find_spec('ethos.ethos'):
            from ethos.ethos.library.ethos import Ethos
        else:
            from ethos.library.ethos import Ethos
        coLib = Ethos()

        sis_messages = coLib.get_messages()
        
        if sis_messages:
            for message in sis_messages:
                if not SIS_Subscription.objects.filter(message__id=message['id']).exists():
                    mesg = SIS_Subscription(
                        message=message
                    )
                    mesg.save()

                    mesg.process()

            messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Found ' + str(len(sis_messages)) + ' messages',
                    'list-group-item-success')
        else:
            messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Found 0 messages',
                    'list-group-item-success')


    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'SIS Messages',
            'api_url': '/ce/api/sis_messages?format=datatables',
            'urls': {
                
            }
        }
    )
    