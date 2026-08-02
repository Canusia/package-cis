import datetime

from django.utils.crypto import get_random_string
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from django.conf import settings
from django.core.mail import send_mail
from django.db.utils import IntegrityError
from django.core.management import call_command
from django.contrib.sites.models import Site

from cis.models.term import AcademicYear, Term
from cis.models.customuser import CustomUser
from cis.models.course import Campus

from cis.middleware import current_request
from cis.models.settings import Setting

class Command(BaseCommand):
    '''
    Create groups in DB
    '''
    help = 'Creates user groups in DB'

    def add_arguments(self, parser):
        parser.add_argument('-d', '--domain', type=str, help='Fully qualified domain')
        parser.add_argument('-p', '--password', type=str, help='Password for admin users')
        # parser.add_argument('-c', '--campus', type=str, help='Campus')

    def handle(self, *args, **kwargs):

        request = current_request()

        Setting.objects.all().delete()

        call_command('loaddata', 'setting_data.json')