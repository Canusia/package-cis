"""
Cron Views
"""
import csv, io, logging

from django.conf import settings
from django.db import IntegrityError
from django.utils.safestring import mark_safe
from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt
from django.template.loader import get_template, render_to_string


logger = logging.getLogger(__name__)

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from rest_framework.decorators import api_view 
from rest_framework.response import Response

from cis.models.crontab import CronLog
from cis.serializers.cron import CronLogSerializer
from cis.utils import CIS_user_only
from cis.menu import cis_menu, draw_menu

class CronLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CronLogSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        records = CronLog.objects.all()
        return records

def index(request):
    menu = draw_menu(cis_menu, 'users', 'cron')
    template = 'cis/cron/index.html'
    
    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'Scheduled Tasks',
            'api_url': '/ce/api/cronlog?format=datatables',
        }
    )
