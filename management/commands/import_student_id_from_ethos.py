"""
Look up SIS identity (sis_id / psid / username) from Ethos for students
currently awaiting an ID (application_status='in_review').

Wired to the `student_id_importer` setting + CronTab (see cis/settings/).
"""
import csv
import datetime
import json
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.http import HttpResponse
from django.template import Context, Template

from mailer import send_mail

from cis.models.student import Student
from cis.services.tenant_services import get_tenant_service
from cis.settings.student_id_importer import student_id_importer
from cis.signals.crontab import cron_task_done, cron_task_started
from cis.storage_backend import PrivateMediaStorage
from cis.utils import get_s3_url

logger = logging.getLogger(__name__)


def _send_done(cls, time, summary, rows):
    cron_task_done.send(
        sender=cls,
        task=cls,
        scheduled_time=time,
        summary=summary,
        detailed_log=json.dumps(rows),
    )


class Command(BaseCommand):
    """Look up Banner SIS identity from Ethos for in_review students."""

    help = 'Look up SIS identity from Ethos for students with application_status=in_review'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Scheduled run time (for cron signals)')

    def handle(self, *args, **kwargs):
        configs = student_id_importer.from_db()
        ethos_identity = get_tenant_service('ethos_identity')
        time = kwargs.get('time')

        if time:
            cron_task_started.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time,
            )

        if configs.get('is_active') != 'Yes':
            return

        rows = []

        type_id = ethos_identity.get_alt_credential_type_id()
        if not type_id:
            summary = 'Aborted: alternativeCredentials type UUID not configured in SIS settings.'
            logger.error(summary)
            if time:
                _send_done(self.__class__, time, summary, rows)
            return

        candidates = Student.objects.filter(
            application_status='in_review'
        ).select_related('user')

        total = candidates.count()
        updated = no_match = no_change = errors = 0

        for record in candidates.iterator():
            person = ethos_identity.lookup_ethos_person_for_student(record, type_id=type_id)
            if not person:
                rows.append({'id': str(record.id), 'RESULT': 'No match in Ethos'})
                no_match += 1
                continue

            changes, error = ethos_identity.apply_ethos_identity(record, person, actor=None)
            if error:
                rows.append({'id': str(record.id), 'RESULT': f'Error: {error}'})
                errors += 1
            elif changes:
                rows.append({
                    'id': str(record.id),
                    'RESULT': 'Updated: ' + '; '.join(changes),
                })
                updated += 1
            else:
                rows.append({'id': str(record.id), 'RESULT': 'No changes (already in sync)'})
                no_change += 1

        summary_lines = [
            f'Checked {total} students (application_status=in_review).',
            f'Updated: {updated}',
            f'No match in Ethos: {no_match}',
            f'Already in sync: {no_change}',
            f'Errors: {errors}',
        ]

        # Write results CSV if we have rows.
        results_url = None
        if rows:
            now = datetime.datetime.now()
            name_tmpl = Template(configs.get('path_to_results_file') or 'student_id_from_ethos_{{yyyy}}{{mm}}{{dd}}_{{hh}}.csv')
            results_file_name = name_tmpl.render(Context({
                'hh': now.strftime('%H'),
                'mm': now.strftime('%m'),
                'dd': now.strftime('%d'),
                'yyyy': now.strftime('%Y'),
            }))

            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{results_file_name}"'
            writer = csv.writer(response)
            writer.writerow(['id', 'RESULT'])
            for row in rows:
                writer.writerow([row['id'], row['RESULT']])

            try:
                path = PrivateMediaStorage().save(results_file_name, ContentFile(response.getvalue()))
                results_url = get_s3_url(path)
                summary_lines.append(f'Results file: {results_url}')
            except Exception as e:
                logger.error('import_student_id_from_ethos: failed to save results file: %s', e)

        summary = '\r\n'.join(summary_lines)

        notification_list = (configs.get('notification_list') or '').split(',')
        notification_list = [addr.strip() for addr in notification_list if addr.strip()]
        if notification_list:
            try:
                send_mail(
                    'Student ID Lookup from Ethos',
                    summary,
                    settings.DEFAULT_FROM_EMAIL,
                    notification_list,
                )
            except Exception as e:
                logger.error('import_student_id_from_ethos: notify failed: %s', e)

        if time:
            _send_done(self.__class__, time, summary, rows)
