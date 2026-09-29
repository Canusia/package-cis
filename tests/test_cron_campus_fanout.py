"""MC-04: cron_jobs / hourly_jobs run scheduled commands once per campus.

The CronTab-scheduled commands fan out per campus inside campus_context();
the deployment-wide housekeeping (mail queue, purges, stats) runs once.
"""
import uuid
from unittest import mock

from django.conf import settings
from django.core.management import call_command as real_call_command
from django.test import TestCase, override_settings

from cis.campus_context import current_campus_or_none
from cis.models.course import Campus
from cis.models.crontab import CronTab


class CronFanOutTests(TestCase):
    def setUp(self):
        Campus.objects.all().delete()
        self.campuses = [
            Campus.objects.create(name=f'{n}-{uuid.uuid4().hex[:6]}',
                                  code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')
            for n in ('C1', 'C2')]
        CronTab.objects.create(command='probe_job', cron='* * * * *')
        self.calls = []

    def _fake_call(self, name, *args, **kwargs):
        if name in ('cron_jobs', 'hourly_jobs'):
            return real_call_command(name, *args, **kwargs)
        self.calls.append((name, current_campus_or_none()))

    def _run(self, command):
        with mock.patch(f'cis.management.commands.{command}.call_command',
                        side_effect=self._fake_call), \
                mock.patch('cis.models.crontab.CronTab.schedule_upcoming_tasks'), \
                mock.patch('ses_tracking.models.DailyEmailStats.is_bounce_rate_acceptable',
                           return_value=True):
            real_call_command(command)
        return self.calls

    def _job_campuses(self, calls):
        return [campus for name, campus in calls if name == 'probe_job']

    @override_settings(MULTI_CAMPUS=True, MYCE_CRON_INTERVAL=5)
    def test_cron_jobs_fans_out_scheduled_commands(self):
        calls = self._run('cron_jobs')
        self.assertEqual(sorted(c.pk for c in self._job_campuses(calls)),
                         sorted(c.pk for c in self.campuses))
        self.assertEqual([n for n, _ in calls].count('send_mail'), 1)

    @override_settings(MULTI_CAMPUS=True)
    def test_hourly_jobs_fans_out_scheduled_commands(self):
        calls = self._run('hourly_jobs')
        self.assertEqual(len(self._job_campuses(calls)), 2)
        self.assertEqual([n for n, _ in calls].count('send_mail'), 1)

    @override_settings(MYCE_CRON_INTERVAL=5)
    def test_single_campus_runs_scheduled_commands_once(self):
        calls = self._run('cron_jobs')
        self.assertEqual(len(self._job_campuses(calls)), 1)
