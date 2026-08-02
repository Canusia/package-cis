# users/models.py
import uuid, datetime, logging
from django.db import models
from django.db.models import JSONField

from model_utils import FieldTracker

from cron_validator import CronValidator

from cis.storage_backend import PrivateMediaStorage


logger = logging.getLogger(__name__)

def cron_log_upload_path(instance, filename):
    return f'cron_logs/{instance.id}/{filename}'

class CronLog(models.Model):
    cron = models.ForeignKey('cis.CronTab', on_delete=models.CASCADE)
    
    run_completed_on = models.DateTimeField(blank=True, null=True)
    run_started_on = models.DateTimeField(blank=True, null=True)
    
    run_scheduled_for = models.DateTimeField(blank=True, null=True)

    meta = JSONField(default=dict)

    log_file = models.FileField(
        storage=PrivateMediaStorage(),
        blank=True,
        upload_to=cron_log_upload_path
    )

    class Meta:
        ...

    @property
    def summary(self):
        return self.meta.get('summary', '')
    
    @property
    def command(self):
        return self.cron.command

class CronTab(models.Model):
    cron = models.CharField(max_length=20)
    command = models.CharField(max_length=100, unique=True)

    last_run_completed_on = models.DateTimeField(blank=True, null=True)
    last_run_started_on = models.DateTimeField(blank=True, null=True)

    last_modified_on = models.DateTimeField(blank=True, null=True)

    tracker = FieldTracker(fields=['cron'])

    def __str__(self):
        return self.command

    @classmethod
    def started_run(cls, command):
        cron = CronTab.objects.get(command=command)
        cron.last_run_started_on = datetime.datetime.now()
        cron.save()
        
    @classmethod
    def completed_run(cls, command):
        cron = CronTab.objects.get(command=command)
        cron.last_run_completed_on = datetime.datetime.now()
        cron.save()

    @classmethod
    def update_tasks_for_command(cls, command):
        current_time = datetime.datetime.now()

        # Remove all future commands for 'command'

        CronLog.objects.filter(
            cron__command=command,
            run_scheduled_for__gte=current_time
        ).delete()

    @classmethod
    def schedule_upcoming_tasks(cls, hours=24):

        top_of_hour = datetime.datetime.now().replace(
            microsecond=0,
            second=0,
            minute=0
        )

        end_hour = top_of_hour + datetime.timedelta(hours=hours)
        jobs = CronTab.objects.all()

        for job in jobs:
            try:
                executors = CronValidator.get_execution_time(
                    job.cron,
                    from_dt=top_of_hour,
                    to_dt=end_hour
                )
    
                if executors:
                    for executor in executors:

                        if not CronLog.objects.filter(
                            cron=job,
                            run_scheduled_for=executor
                        ).exists():
                            log_entry = CronLog(
                                cron=job,
                                run_scheduled_for=executor
                            )

                            try:
                                log_entry.save()
                            except:
                                ...


            except Exception as e:
                logger.error(job.cron)
                logger.error(e)    
