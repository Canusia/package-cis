from django.core.management.base import BaseCommand

from cis.management.campus_command import CampusCommand
import os, csv, logging

from django.utils.safestring import mark_safe

from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import get_template
from django.conf import settings

logger = logging.getLogger(__name__)

from cis.models.section import StudentRegistration

class Command(CampusCommand):
    '''
    Notify counselors who have pending applications
    '''
    help = 'Notify school counselors who have pending applications'

    def add_arguments(self, parser):
        super().add_arguments(parser)  # --campus (MC-11)
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        StudentRegistration.notify_school_counselors(*args, **kwargs)
        # StudentRegistration.notify_homeschool_parents(*args, **kwargs)
