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

from cis.utils import (
    get_uploaded_file, active_term,
    registration_terms, is_student_registration_open
)
from cis.models.sis import SIS_Log, SIS_LogSerializer

logger = logging.getLogger(__name__)

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from rest_framework.decorators import api_view 
from rest_framework.response import Response

from cis.utils import CIS_user_only, FACULTY_user_only, INSTRUCTOR_user_only
from cis.menu import cis_menu, draw_menu

from ..serializers.note import StudentNoteSerializer

class SIS_LogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SIS_LogSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        records = SIS_Log.objects.all()

        return records

@xframe_options_exempt
def detail(request, record_id):
    """
    Record details page
    """
    template = 'cis/students/sis_log.html'
    record = get_object_or_404(SIS_Log, pk=record_id)

    return render(
        request,
        template, {
            'page_title': "SIS Log",
            'record': record,
        })

def index(request):
    menu = draw_menu(cis_menu, 'students', 'sis_logs')
    template = 'cis/students/sis_logs.html'
    
    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'SIS Logs',
            'api_url': '/ce/api/sis_logs?format=datatables',
            'urls': {
                
            }
        }
    )
    