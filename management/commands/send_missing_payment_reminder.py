import os, csv, datetime, logging, io, json

from django.conf import settings
from django.db.utils import IntegrityError
from django.core.management.base import BaseCommand

from cis.utils import upload_to_s3
from cis.models.student import Student
from cis.models.section import StudentRegistration

from cis.signals.crontab import cron_task_done, cron_task_started

from cis.settings.registration_status_email import registration_status_email
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    '''
    Sending Missing Payment Reminders
    '''
    help = 'Sending Missing Payment Reminders'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        from cis.utils import is_student_registration_open, is_student_billpay_open, registration_terms, active_term

        from cis.settings.registration_charges import registration_charges
        config = registration_charges.from_db()

        summary = ''
        detailed_log = {
            'successfully_sent': 0,
            'sent': [],
            'failed_to_send': 0,
            'fails': []
        }

        mode = config.get('mode', 'debug')
        if kwargs.get('time'):
            time = kwargs['time']

            cron_task_started.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time
            )

        if not is_student_billpay_open():
            summary = 'Student Bill Pay is Closed'

            if kwargs.get('time'):
                cron_task_done.send(
                    sender=self.__class__,
                    task=self.__class__,
                    scheduled_time=time,
                    summary=summary,
                    detailed_log=json.dumps(detailed_log)
                )

            students = Student.objects.none()
        else:
            # get all registrations that have needs_mirroring set

            registrations = StudentRegistration.objects.filter(
                class_section__registration_term__in=registration_terms()
            )

            students = Student.objects.filter(
                id__in=registrations.values_list('student__id'),
                current_student_balance__gt=0
            )


        
        summary += 'Found ' + str(students.count()) + ' records to notify'
        term = active_term() 
        balance = 0
        for record in students:
            record.send_payment_url(term.id, mode)
            detailed_log['successfully_sent'] += 1
            detailed_log['sent'].append(record.user.email)

            balance += record.current_student_balance

            if mode.lower() != 'debug':
                record.add_note(None, f'Sent payment reminder {record.current_student_balance}')

        summary += "\r\nSuccessfully sent - " + str(detailed_log['successfully_sent'])
        summary += "\r\Total Balance - " + str(balance)
        
        if kwargs.get('time'):
            cron_task_done.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time,
                summary=summary,
                detailed_log=json.dumps(detailed_log)
            )
        else:
            logger.error(summary)
            logger.error(detailed_log)

