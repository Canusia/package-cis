import os, csv, datetime, logging, io, json, zlib

from django.conf import settings
from django.db import connection
from django.db.utils import IntegrityError
from django.core.management.base import BaseCommand

from cis.campus_context import current_campus_or_none, scope_to_current_campus
from cis.utils import upload_to_s3
from cis.models.student import Student
from cis.models.section import StudentRegistration
from cis.services.tenant_services import get_tenant_service

from cis.signals.crontab import cron_task_done, cron_task_started

import importlib.util
if importlib.util.find_spec('ethos.ethos'):
    from ethos.ethos.library.ethos import Ethos
else:
    from ethos.library.ethos import Ethos
from cis.settings.registration_status_email import registration_status_email
logger = logging.getLogger(__name__)

# Postgres advisory-lock key for this command ('SIS1'), paired with a per-campus
# key. A run takes 20-25 minutes on a 30-minute schedule; without the lock an
# overlapping run mirrors from a second stale snapshot of the queue (2026-10-08
# incident). Per campus because multi-campus runs the command once per campus.
RUN_LOCK_KEY = 0x53495331


def campus_lock_key(campus_id):
    """32-bit second key for the campus (0 for none / single-campus)."""
    if campus_id is None:
        return 0
    return zlib.crc32(str(campus_id).encode()) & 0x7FFFFFFF


def _run_lock_keys():
    campus = current_campus_or_none()
    return [RUN_LOCK_KEY, campus_lock_key(campus.pk if campus else None)]


def _try_run_lock(keys):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s, %s)', keys)
        return cursor.fetchone()[0]


def _release_run_lock(keys):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock(%s, %s)', keys)

class Command(BaseCommand):
    '''
    Mirror registrations to SIS
    '''
    help = 'Mirror registrations to SIS'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        keys = _run_lock_keys()
        if not _try_run_lock(keys):
            message = 'Skipped: previous run still in progress'
            logger.warning('send_registrations_to_sis: %s', message)
            if kwargs.get('time'):
                cron_task_started.send(
                    sender=self.__class__, task=self.__class__,
                    scheduled_time=kwargs['time'])
                cron_task_done.send(
                    sender=self.__class__, task=self.__class__,
                    scheduled_time=kwargs['time'], summary=message,
                    detailed_log=json.dumps({'skipped': message}))
            return
        try:
            self._run(*args, **kwargs)
        finally:
            _release_run_lock(keys)

    def _run(self, *args, **kwargs):
        config = registration_status_email.from_db()

        summary = ''
        detailed_log = {
            'total_registrations': {},
            'successfully_sent': 0,
            'total_no_sis_id': 0,
            'no_sis': [],
            'failed_to_send': 0,
            'fails': [],
            'no_parent_consent': [],
            'total_no_parent_consent': 0
        }

        mirror_status = config.get('sis_mirror_trigger')
        for status in mirror_status:
            detailed_log[f'{status}_success_count'] = 0
            detailed_log[f'{status}_success_list'] = []

            detailed_log[f'{status}_fail_count'] = 0
            detailed_log[f'{status}_fail_list'] = []

        if kwargs.get('time'):
            time = kwargs['time']

            cron_task_started.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time
            )

        # Single source of truth — same selection the Pending SIS Mirror tab shows.
        # Multi-campus: cron runs this once per campus (run_for_each_campus), so each
        # run takes only its own campus's registrations. Single-campus: unchanged.
        registrations = scope_to_current_campus(
            StudentRegistration.objects.pending_sis_mirror(mirror_status),
            'class_section__course__campus')

        summary += 'Found ' + str(registrations.count()) + ' records to send'
        detailed_log['total_registrations'] = registrations.count()

        for record in registrations:
            if record.is_held_for_parent_consent:
                detailed_log['no_parent_consent'].append(str(record.id))
                detailed_log['total_no_parent_consent'] += 1
                continue

            try:
                result, rez = get_tenant_service('registration').mirror_to_sis(record)
            except Exception as e:
                result = False
                rez = []

            if result:
                detailed_log['successfully_sent'] += 1

                for mesg in rez:
                    if 'success' in mesg:
                        detailed_log['successfully_sent'] += 1

                        if not detailed_log.get(f'{record.status}_success_count'):
                            detailed_log[f'{record.status}_success_count'] = 0
                            detailed_log[f'{record.status}_success_list'] = []

                        detailed_log[f'{record.status}_success_count'] += 1
                        detailed_log[f'{record.status}_success_list'].append(str(record.id))

                        StudentRegistration.objects.filter(
                            id=record.id
                        ).update(
                            needs_mirroring=False
                        )
                        
                    if 'failed to process' in mesg:
                        detailed_log['failed_to_send'] += 1
                        detailed_log['fails'].append(str(record.id))

                        if not detailed_log.get(f'{record.status}_fail_count'):
                            detailed_log[f'{record.status}_fail_count'] = 0
                            detailed_log[f'{record.status}_fail_list'] = []

                        # A failed row stays queued unless its error is marked
                        # "Stop mirroring when these errors happen again" in the
                        # registration status email setting (mirror_to_sis
                        # applies that); this used to drop every failure.

                        detailed_log[f'{record.status}_fail_count'] += 1
                        detailed_log[f'{record.status}_fail_list'].append(str(record.id))
            else:
                detailed_log['failed_to_send'] += 1
                detailed_log['fails'].append(str(record.id))

                for mesg in rez:
                    if 'no sis id' in mesg:
                        detailed_log['total_no_sis_id'] += 1
                        detailed_log['no_sis'].append(str(record.student.id))
            
        summary += "\r\nSuccessfully sent - " + str(detailed_log['successfully_sent'])
        summary += "\r\nFailed to send - " + str(detailed_log['failed_to_send'])
        summary += "\r\nHeld for parent consent - " + str(detailed_log['total_no_parent_consent'])

        if kwargs.get('time'):
            time = kwargs.get('time')
            
            cron_task_done.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time,
                summary=summary,
                detailed_log=json.dumps(detailed_log)
            )

