"""
Pull ClassSections from the SIS (Ethos) for each term selected in the
`class_section_importer` setting.

Wired to the setting + CronTab; emits cron_task_started / cron_task_done
signals so runs are tracked alongside other cron-driven imports.
"""
import csv
import datetime
import importlib.util
import io
import json
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.template import Context, Template

from mailer import send_mail

from cis.models.term import Term
from cis.settings.class_section_importer import class_section_importer
from cis.signals.crontab import cron_task_done, cron_task_started
from cis.storage_backend import PrivateMediaStorage
from cis.utils import get_s3_url

if importlib.util.find_spec('ethos.ethos'):
    from ethos.ethos.tasks import import_sections_for_term
else:
    from ethos.tasks import import_sections_for_term

logger = logging.getLogger(__name__)


def _send_done(cls, time, summary, rows):
    cron_task_done.send(
        sender=cls,
        task=cls,
        scheduled_time=time,
        summary=summary,
        detailed_log=json.dumps(rows),
    )


def _format_counts(counts):
    parts = []
    for key in ('section_created', 'section_updated', 'section_skipped'):
        if key in counts:
            label = key.replace('section_', '')
            parts.append(f"{counts[key]} {label}")
    return ', '.join(parts) if parts else 'no counts reported'


class Command(BaseCommand):
    help = 'Pull ClassSections from SIS for the terms selected in the class_section_importer setting.'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Scheduled run time (for cron signals)')

    def handle(self, *args, **kwargs):
        configs = class_section_importer.from_db()
        time = kwargs.get('time')

        if time:
            cron_task_started.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time,
            )

        if configs.get('is_active') != 'Yes':
            if time:
                _send_done(self.__class__, time, 'Skipped: importer is disabled.', [])
            return

        term_ids = configs.get('terms') or []
        if not term_ids:
            summary = 'Skipped: no terms selected in setting.'
            logger.warning(summary)
            if time:
                _send_done(self.__class__, time, summary, [])
            return

        terms_by_id = {
            str(t.id): t
            for t in Term.objects.filter(id__in=term_ids).select_related('academic_year')
        }

        rows = []
        for term_id in term_ids:
            term = terms_by_id.get(str(term_id))
            if not term:
                rows.append({
                    'term_id': str(term_id),
                    'term_code': '',
                    'term_label': '',
                    'status': 'error',
                    'counts': None,
                    'error': 'Term not found in database',
                })
                continue

            try:
                # `import_sections_for_term` is a django-tasks @task, i.e. a
                # Task object, not a function — calling it directly raises
                # "TypeError: 'Task' object is not callable". `.call()` runs it
                # inline and returns the counts dict this command needs.
                result = import_sections_for_term.call(str(term.id))
            except Exception as e:
                logger.error('import_class_sections: term %s failed: %s', term.code, e, exc_info=True)
                rows.append({
                    'term_id': str(term.id),
                    'term_code': term.code,
                    'term_label': term.label,
                    'status': 'error',
                    'counts': None,
                    'error': str(e),
                })
                continue

            if isinstance(result, dict) and result.get('error'):
                rows.append({
                    'term_id': str(term.id),
                    'term_code': term.code,
                    'term_label': term.label,
                    'status': 'error',
                    'counts': None,
                    'error': result['error'],
                })
            else:
                rows.append({
                    'term_id': str(term.id),
                    'term_code': term.code,
                    'term_label': term.label,
                    'status': 'ok',
                    'counts': result if isinstance(result, dict) else {},
                    'error': None,
                })

        results_url = self._write_results_csv(configs, rows)

        summary_lines = [f'Imported sections for {len(rows)} term(s).', '']
        for row in rows:
            header = f"Term {row['term_code']} ({row['term_label']})" if row['term_code'] else f"Term <unknown id={row['term_id']}>"
            if row['status'] == 'ok':
                summary_lines.append(f"{header}: {_format_counts(row['counts'] or {})}")
            else:
                summary_lines.append(f"{header}: Error — {row['error']}")
        if results_url:
            summary_lines += ['', f'Results file: {results_url}']
        summary = '\r\n'.join(summary_lines)

        notification_list = (configs.get('notification_list') or '').split(',')
        notification_list = [addr.strip() for addr in notification_list if addr.strip()]
        if notification_list:
            try:
                send_mail(
                    'Class Section Import from SIS',
                    summary,
                    settings.DEFAULT_FROM_EMAIL,
                    notification_list,
                )
            except Exception as e:
                logger.error('import_class_sections: notify failed: %s', e)

        if time:
            _send_done(self.__class__, time, summary, rows)

    def _write_results_csv(self, configs, rows):
        if not rows:
            return None

        now = datetime.datetime.now()
        name_tmpl = Template(
            configs.get('path_to_results_file')
            or 'class_section_import_{{yyyy}}{{mm}}{{dd}}_{{hh}}.csv'
        )
        results_file_name = name_tmpl.render(Context({
            'hh': now.strftime('%H'),
            'mm': now.strftime('%m'),
            'dd': now.strftime('%d'),
            'yyyy': now.strftime('%Y'),
        }))

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            'term_id', 'term_code', 'term_label', 'status',
            'section_created', 'section_updated', 'section_skipped',
            'error',
        ])
        for row in rows:
            counts = row.get('counts') or {}
            writer.writerow([
                row['term_id'],
                row['term_code'],
                row['term_label'],
                row['status'],
                counts.get('section_created', ''),
                counts.get('section_updated', ''),
                counts.get('section_skipped', ''),
                row.get('error') or '',
            ])

        try:
            path = PrivateMediaStorage().save(results_file_name, ContentFile(buf.getvalue().encode('utf-8')))
            return get_s3_url(path)
        except Exception as e:
            logger.error('import_class_sections: failed to save results file: %s', e)
            return None
