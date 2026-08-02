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

class Command(BaseCommand):
    '''
    Create groups in DB
    '''
    help = 'Creates user groups in DB'

    def add_arguments(self, parser):
        ...
        # parser.add_argument('-d', '--domain', type=str, help='Fully qualified domain')
        # parser.add_argument('-p', '--password', type=str, help='Password for admin users')
        # parser.add_argument('-c', '--campus', type=str, help='Campus')

    def handle(self, *args, **kwargs):

        request = current_request()

        from cis.models.course import Course, Cohort
        from cis.models.district import District
        from cis.models.highschool import HighSchool

        from cis.models.highschool_administrator import HSAdministrator, HSPosition, HSAdministratorPosition

        if not District.objects.filter(name='D1').exists():
            district = District(name='D1', status='Active')
            district.save()
        else:
            district = District.objects.get(name='D1')

        if not HighSchool.objects.filter(
            name='HS1'
        ).exists():
            highschool = HighSchool(
                name='HS1',
                district=district,
                code='123',
                sau='123'
            )
            highschool.save()
        else:
            highschool = HighSchool.objects.get(
                name='HS1'
            )

        if not HSAdministrator.objects.filter(
            user__email='hs_admin@hs.edu'
        ).exists():
            hsadmin = HSAdministrator.create_new(
                'HS', 'Admin',
                'hs_admin@hs.edu',
                '123-123-1234'
            )
        else:
            hsadmin = HSAdministrator.objects.get(
                user__email='hs_admin@hs.edu'
            )

        hsposition = HSPosition.get_or_add(
            'HS Role 1'
        )
        
        hs_admin_position = HSAdministratorPosition(
            hsadmin=hsadmin,
            position=hsposition,
            highschool=highschool,
            status='Active'
        )

        hs_admin_position.save()
