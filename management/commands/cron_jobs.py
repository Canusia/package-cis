import logging, datetime
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.conf import settings

from cron_validator import CronValidator

from django.utils import timezone

from cis.management.campus_command import run_for_each_campus
from cis.models.crontab import CronLog, CronTab

logger = logging.getLogger(__name__)


def due_runs(now, interval):
    """{command: scheduled time} for jobs due in the tick at `now`.

    A tick covers the `interval` minutes up to and including `now`
    ([now - (interval - 1), now], to the minute), so a job runs at the first
    tick at or after its scheduled time -- never early -- and back-to-back
    ticks don't overlap. Runs whose CronLog is already marked as started are
    skipped, so a run is never repeated (#117)."""
    end = now.replace(microsecond=0, second=0)
    start = end - datetime.timedelta(minutes=int(interval) - 1)

    job_queue = {}
    for job in CronTab.objects.all():
        executors = CronValidator.get_execution_time(
            job.cron, from_dt=start, to_dt=end
        )

        for executor in executors or []:
            scheduled_for = executor
            if timezone.is_naive(scheduled_for):
                scheduled_for = timezone.make_aware(scheduled_for)
            if CronLog.objects.filter(
                cron=job,
                run_scheduled_for=scheduled_for,
                run_started_on__isnull=False,
            ).exists():
                continue
            job_queue[job.command] = str(executor)

    return job_queue


class Command(BaseCommand):
    '''
    Hourly jobs
    '''
    help = ''

    def handle(self, *args, **kwargs):

        CronTab.schedule_upcoming_tasks(hours=24)
        
        try:
            call_command('send_bulk_mail')
        except Exception as e:
            logger.error(e)
        
        job_queue = due_runs(
            datetime.datetime.now(),
            getattr(settings, 'MYCE_CRON_INTERVAL')
        )

        # Scheduled commands run once per campus, each in its own campus
        # context, error handling and lock (MC-04); a single-campus deployment
        # runs them once, as before. The housekeeping around this block is
        # deployment-wide and runs once.
        def run_scheduled_jobs():
            for job in sorted(job_queue):
                scheduled_time = job_queue[job]

                try:
                    call_command(job, time=str(scheduled_time))
                except Exception as e:
                    print('failed for ' + str(job))
                    logger.error(job)
                    logger.error(e)

        run_for_each_campus(__name__.rsplit('.', 1)[-1], run_scheduled_jobs)
        
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
            