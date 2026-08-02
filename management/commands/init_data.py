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
        parser.add_argument('-d', '--domain', type=str, help='Fully qualified domain')
        parser.add_argument('-p', '--password', type=str, help='Password for admin users')
        # parser.add_argument('-c', '--campus', type=str, help='Campus')

    def handle(self, *args, **kwargs):

        request = current_request()

        # call_command('migrate')
        call_command('init_groups')

        Campus.get_or_add(
            getattr(settings, 'CAMPUS_CODE_PREFIX')
        )
        
        site = Site.objects.filter(
            pk=1
        ).update(
            domain=str(request.get_host()),
            name=str(request.get_host())
        )

        try:
            current_year = datetime.datetime.now().year
            acad_year = AcademicYear.get_or_add(
                name=f"{current_year} - " + str(current_year+1)
            )

            term = Term.get_or_add(
                academic_year=acad_year,
                label='Fall ' + str(current_year),
                # year=current_year,
                code='FA'+str(current_year)
            )
            print(f'Adding term - {term}')
        except Exception as e:
            print(e)

        try:
            admin_users = settings.MANAGERS
            ce_group = Group.objects.get(
                name='ce'
            )

            for username, email in admin_users:
                print(username, email)
                try:
                    admin_user = CustomUser.objects.get(
                        email=email
                    )

                    ce_group.user_set.add(admin_user)
                    admin_user.is_staff = True
                    admin_user.is_admin = True
                    admin_user.is_superuser = True
                    admin_user.save()
                   
                    ce_group.user_set.add(admin_user)
                    print(f'Updating {username}')


                except CustomUser.DoesNotExist:
                    admin_user = CustomUser(
                        email=email,
                        username=username
                    )
                    pwd = get_random_string(12)
                    admin_user.set_password(
                        kwargs.get('password', pwd)
                    )

                    send_mail(
                        request.get_host(),
                        pwd,
                        settings.DEFAULT_FROM_EMAIL,
                        [email],
                        fail_silently=True,
                    )
                    admin_user.is_staff = True
                    admin_user.is_admin = True
                    admin_user.is_superuser = True
                    admin_user.save()
                   
                    ce_group.user_set.add(admin_user)
                    print(f'Adding {username}')
                    
                except Exception as e:
                    print(f'Unable to find/add admin role to {username}')
                    print(e)
        except Exception as e:
            print(e)