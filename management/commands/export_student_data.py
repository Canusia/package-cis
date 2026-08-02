import logging, json

from django.core.management.base import BaseCommand
from django.conf import settings

logger = logging.getLogger(__name__)

from cis.settings.student_exporter import student_exporter
from cis.signals.crontab import cron_task_done, cron_task_started

class Command(BaseCommand):
    '''
    Import class sections
    '''
    help = 'Export student XML'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        configs = student_exporter.from_db()

        if configs.get('is_active') != 'Yes':
            return

        if kwargs.get('time'):
            time = kwargs['time']

            cron_task_started.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time
            )

        from cis.reports.undup_students import undup_students
        exporter = undup_students()

        total_records, file_path = exporter.run(task=None, data={
            'mark_as_sent': ['1'],
            'send_to_slate': ['1']
        })
        
        summary = f'Sent {total_records} to {file_path}'
        if kwargs.get('time'):
            time = kwargs.get('time')
            
            cron_task_done.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time,
                summary=summary,
                detailed_log=json.dumps(' ')
            )