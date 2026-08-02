import logging, datetime
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.conf import settings

from cron_validator import CronValidator

from cis.models.crontab import CronTab

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    '''
    Hourly jobs
    '''
    help = ''

    def handle(self, *args, **kwargs):
        try:
            try:
                from ethos.ethos.library.ethos import Recruiter, Ethos
            except ImportError:
                from ethos.library.ethos import Recruiter, Ethos
            from cis.models.sis import SIS_Subscription
            from cis.models.student import Student

            coLib = Ethos()
            messages = coLib.get_messages(500)
            if messages:
                for message in messages:

                    if not SIS_Subscription.objects.filter(message__id=message['id']).exists():
                        mesg = SIS_Subscription(
                            message=message
                        )
                        mesg.save()

                        # print(mesg.id)
                        # print(mesg.message)
                        mesg.process()
            else:
                print('no messages found')
        except Exception as e:
            logger.error(e)
            print(e)
