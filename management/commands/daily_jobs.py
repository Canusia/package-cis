import logging, json
from django.core.management import call_command
from django.core.management.base import BaseCommand

from django.conf import settings

logger = logging.getLogger(__name__)

from cis.models.section import StudentRegistration
from cis.models.student import Student

from pypdf import PdfReader, PdfWriter
from typing import Dict, List, Tuple, Optional

import importlib.util
if importlib.util.find_spec('announcement.announcement'):
    from announcement.announcement.models.announcement import BulkMessage, BulkMessageLog
else:
    from announcement.models.announcement import BulkMessage, BulkMessageLog
if importlib.util.find_spec('ethos.ethos'):
    from ethos.ethos.library.ethos import Ethos
else:
    from ethos.library.ethos import Ethos
class Command(BaseCommand):
    '''
    Daily jobs
    '''
    help = ''

    
    def handle(self, *args, **kwargs):
        ethos = Ethos()
        subjects = ethos.get_subjects()
        print(f'Found {len(subjects)} subjects in Ethos.')
        for subject in subjects:
            print(subject.get('abbreviation'), subject.get('title'), subject.get('id')) 
        return
        # guid = ethos.get_academic_period_id('2ZN')
        # print(guid)
        # academic_years = ethos.get_academic_periods(category="year")
        # print(academic_years)
        terms = ethos.get_child_academic_periods('0307e986-df02-4850-b5b8-b8519203f814', depth=1)
        for term in terms:
            print(term.get('title'), term.get('category', {}).get('type'), term.get('code'), term.get('id'))


        periods = ethos.get_child_academic_periods('0307e986-df02-4850-b5b8-b8519203f814')
        for term in periods:
            print(term.get('title'), term.get('category', {}).get('type'), term.get('code'), term.get('id'))