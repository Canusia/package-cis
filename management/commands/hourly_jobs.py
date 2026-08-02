import logging, datetime
from django.core.management import call_command
from django.core.management.base import BaseCommand

from cron_validator import CronValidator

from cis.models.crontab import CronTab

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    '''
    Hourly jobs
    '''
    help = ''

    def handle(self, *args, **kwargs):

        CronTab.schedule_upcoming_tasks()
        
        # this needs to mirror crontab/models.py
        top_of_hour = datetime.datetime.now().replace(
            microsecond=0,
            second=0,
            minute=0
        )

        end_hour = top_of_hour + datetime.timedelta(hours=1)

        # this needs to mirror crontab/models.py
        # top_of_hour = datetime.datetime.now().replace(
        #     microsecond=0,
        #     second=0
        # )

        # end_hour = top_of_hour + datetime.timedelta(minutes=20)

        try:
            call_command('run_reports')
        except Exception as e:
            logger.error(e)
        
        jobs = CronTab.objects.all()
        job_queue = {}

        for job in jobs:
            executors = CronValidator.get_execution_time(
                job.cron,
                from_dt=top_of_hour,
                to_dt=end_hour
            )
            
            if executors:
                for executor in executors:
                    job_queue[job.command] = str(executor)

        for job in sorted(job_queue):   
            scheduled_time = job_queue[job]

            try:
                call_command(job, time=str(scheduled_time))
            except Exception as e:
                print('failed for ' + str(job))
                logger.error(job)
                logger.error(e)
        
        # call this every hour to send emails in queue
        try:
            call_command('send_mail')
        except Exception as e:
            logger.error(e)


        try:
            call_command("purge_mail_log", "10")
        except Exception as e:
            logger.error(e)
