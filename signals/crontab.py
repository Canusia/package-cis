from datetime import datetime
from io import StringIO
import logging

from django.db.models.signals import pre_save, post_save
from django.core.files.base import ContentFile, File
from django import dispatch
from django.dispatch import receiver

from cis.models.crontab import CronTab, CronLog

logger = logging.getLogger(__name__)

cron_task_done = dispatch.Signal([
    "task", "scheduled_time", "summary", "detailed_log"
    ])
cron_task_started = dispatch.Signal([
    "task", "scheduled_time"
    ])

@receiver(pre_save, sender=CronTab)
def cron_changed(sender, instance, **kwargs):
    from datetime import datetime
        
    previous_status = instance.tracker.previous('cron')
    status = instance.cron

    if previous_status != status:
        CronTab.update_tasks_for_command(instance.command)

@receiver(post_save, sender=CronTab)
def update_future_cron(sender, instance, **kwargs):
    from datetime import datetime
        
    previous_status = instance.tracker.previous('cron')
    status = instance.cron

    if previous_status != status:
        CronTab.schedule_upcoming_tasks()

@receiver(cron_task_started)
def cron_started(sender, task, **kwargs):

    task = str(task)
    command = task.split('.')
    command = command[len(command)-2]

    scheduled_time = kwargs.get('scheduled_time')

    # Specify the format of the input string
    format_string = "%Y-%m-%d %H:%M:%S"

    # Convert the string to a datetime object
    scheduled_time = datetime.strptime(scheduled_time, format_string)

    try:
        log_entry = CronLog.objects.filter(
            cron__command=command,
            run_scheduled_for=scheduled_time
        )
        
        if log_entry:
            log_entry = log_entry[0]

            log_entry.run_started_on = datetime.now()
            log_entry.save()
    except Exception as e:
        logger.error(f'MyCE, cron started {command}, {scheduled_time}', exc_info=True)

@receiver(cron_task_done)
def cron_completed(sender, task, **kwargs):

    task = str(task)
    command = task.split('.')
    command = command[len(command)-2]

    scheduled_time = kwargs.get('scheduled_time')

    # Specify the format of the input string
    format_string = "%Y-%m-%d %H:%M:%S"

    # Convert the string to a datetime object
    scheduled_time = datetime.strptime(scheduled_time, format_string)

    try:
        log_entry = CronLog.objects.filter(
            cron__command=command,
            run_scheduled_for=scheduled_time
        )

        if log_entry:
            log_entry = log_entry[0]

            log_entry.run_completed_on = datetime.now()
            log_entry.meta['summary'] = kwargs.get('summary')

            log_entry.log_file.save('log.json', ContentFile(kwargs.get('detailed_log', '').encode()))

            log_entry.save()

    except Exception as e:
        logger.error(f'MyCE, cron ended {command}, {scheduled_time}', exc_info=True)