"""Recompute every student's grade_level from their graduation fact.

``grade_level`` is written once, when an application or profile form is saved,
and nothing recomputed it afterwards — so a student who applied as a sophomore
stayed a sophomore until something re-saved their profile. Tenants that prompt
students to review their profile each term do not help: the "my information is
correct" branch calls ``save()`` directly and never touches ``grade_level``, so
the honest answer is precisely the one that skips the refresh.

Scheduled for the 1st of the rollover month, when the academic year turns over
and every student advances. Safe to run by hand at any time — it is idempotent
and only ever writes a real grade.
"""
import json
from datetime import datetime

from django.core.management.base import BaseCommand

from cis.models.student import Student
from cis.signals.crontab import cron_task_done, cron_task_started


class Command(BaseCommand):

    help = 'Recompute student grade levels from graduation year/date'

    def add_arguments(self, parser):
        parser.add_argument(
            '-t', '--time', type=str,
            default=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            help='Scheduled time of run (default: now). "YYYY-MM-DD HH:MM:SS"')
        parser.add_argument(
            '--dry-run', action='store_true', default=False,
            help='Report what would change without writing anything.')

    def handle(self, *args, **kwargs):
        time = kwargs['time']
        dry_run = kwargs['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING(
                'DRY RUN — no grade levels will be written.\n'))

        cron_task_started.send(
            sender=self.__class__, task=self.__class__, scheduled_time=time)

        processed = changed = skipped = errors = 0
        detail = []

        students = Student.objects.exclude(
            graduation_date__isnull=True, graduation_year__isnull=True)

        for student in students.iterator():
            processed += 1
            previous = student.grade_level or ''
            try:
                computed = student.refresh_grade_level_from_graduation(
                    save=not dry_run)
            except Exception as e:                       # noqa: BLE001
                errors += 1
                detail.append({'student': str(student.pk), 'error': str(e)})
                continue

            if computed is None:
                # Derivation produced a sentinel; the existing value stands.
                skipped += 1
            elif computed != previous:
                changed += 1
                detail.append({'student': str(student.pk),
                               'from': previous, 'to': computed})
                if dry_run:
                    self.stdout.write(
                        f'  {student.pk}: {previous or "(blank)"} -> {computed}')

        summary = (f'{processed} student(s) processed, {changed} changed, '
                   f'{skipped} left alone, {errors} error(s)')
        if dry_run:
            summary = f'[DRY RUN] {summary}'
        self.stdout.write(self.style.SUCCESS(summary))

        cron_task_done.send(
            sender=self.__class__, task=self.__class__, scheduled_time=time,
            summary=summary, detailed_log=json.dumps(detail))
