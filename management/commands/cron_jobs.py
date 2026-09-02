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

        CronTab.schedule_upcoming_tasks(hours=24)
        
        # this needs to mirror crontab/models.py
        cron_scheduler_start_time = datetime.datetime.now().replace(
            microsecond=0,
            second=0
        )

        cron_scheduler_end_time = cron_scheduler_start_time + datetime.timedelta(
            minutes=getattr(settings, 'MYCE_CRON_INTERVAL')
        )
        
        try:
            call_command('send_bulk_mail')
        except Exception as e:
            logger.error(e)
        
        jobs = CronTab.objects.all()
        job_queue = {}

        for job in jobs:
            executors = CronValidator.get_execution_time(
                job.cron,
                from_dt=cron_scheduler_start_time,
                to_dt=cron_scheduler_end_time
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
        
        from ses_tracking.models import DailyEmailStats
        if DailyEmailStats.is_bounce_rate_acceptable():
            try:
                call_command('send_mail')
            except Exception as e:
                logger.error(e)
                print('failed for send mail')

        try:
            call_command(
                "aggregate_daily_stats",
                date=datetime.date.today().isoformat(),
                force=True
            )
        except Exception as e:
            logger.error(f"Error aggregating daily stats: {e}")

        try:
            call_command(
                "purge_mail_log",
                getattr(settings, 'MYCE_PURGE_MAIL_LOG_INTERVAL')
            )
        except Exception as e:
            logger.error(e)

        try:
            call_command(
                "purge_sis_logs",
                100
            )
        except Exception as e:
            logger.error(e)

        try:
            call_command(
                "prune_db_task_results",
                '--min-age-days=30'
            )
        except Exception as e:
            logger.error(e)
            