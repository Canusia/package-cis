"""package-cis#117: cron_jobs runs a job at the first tick at or after its
scheduled time -- never early, never twice, never skipped (a 1:55 job ran at
the 1:50 tick; one saved at 11:33 for 11:35 never ran; a job on a tick
boundary fell in two windows)."""

from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from cis.management.commands.cron_jobs import due_runs
from cis.models.crontab import CronLog, CronTab


class DueRunsTests(TestCase):

    def setUp(self):
        CronTab.objects.all().delete()  # jobs other packages seed
        self.job = CronTab.objects.create(
            cron='55 13 * * *', command='notify_missing_syllabi')

    def set_cron(self, cron):
        self.job.cron = cron
        self.job.save()

    def test_not_run_before_scheduled_time(self):
        self.assertEqual(due_runs(datetime(2026, 10, 23, 13, 50), 10), {})

    def test_run_at_first_tick_after_scheduled_time(self):
        self.assertEqual(
            due_runs(datetime(2026, 10, 23, 14, 0, 7), 10),
            {'notify_missing_syllabi': '2026-10-23 13:55:00'})

    def test_run_at_tick_equal_to_scheduled_time(self):
        self.set_cron('50 13 * * *')
        self.assertEqual(
            due_runs(datetime(2026, 10, 23, 13, 50), 10),
            {'notify_missing_syllabi': '2026-10-23 13:50:00'})

    def test_run_on_a_tick_boundary_is_not_repeated(self):
        # 13:50 is in both the 13:50 and 14:00 windows when the interval is 10
        self.set_cron('50 13 * * *')
        self.assertEqual(
            due_runs(datetime(2026, 10, 23, 13, 50), 10),
            {'notify_missing_syllabi': '2026-10-23 13:50:00'})
        self.assertEqual(due_runs(datetime(2026, 10, 23, 14, 0), 10), {})

    def test_interval_nine_with_ten_minute_ticks_leaves_no_gap(self):
        # ewu and others set MYCE_CRON_INTERVAL=9 while ticks are */10
        self.set_cron('51 13 * * *')
        self.assertEqual(due_runs(datetime(2026, 10, 23, 13, 50), 9), {})
        self.assertEqual(
            due_runs(datetime(2026, 10, 23, 14, 0), 9),
            {'notify_missing_syllabi': '2026-10-23 13:51:00'})

    def test_interval_nine_does_not_run_twice(self):
        self.set_cron('50 13 * * *')
        due_runs(datetime(2026, 10, 23, 13, 50), 9)
        self.assertEqual(due_runs(datetime(2026, 10, 23, 14, 0), 9), {})

    def test_job_saved_between_ticks_runs_at_next_tick(self):
        # saved at 11:33 for 11:35; ticks at 11:30 and 11:40
        self.set_cron('35 11 * * *')
        self.assertEqual(due_runs(datetime(2026, 10, 23, 11, 30), 10), {})
        self.assertEqual(
            due_runs(datetime(2026, 10, 23, 11, 40), 10),
            {'notify_missing_syllabi': '2026-10-23 11:35:00'})

    def test_interval_may_be_a_string(self):
        # MYCE_CRON_INTERVAL can come straight from os.getenv
        self.assertEqual(
            due_runs(datetime(2026, 10, 23, 14, 0), '10'),
            {'notify_missing_syllabi': '2026-10-23 13:55:00'})

    def test_already_started_run_is_skipped(self):
        CronLog.objects.create(
            cron=self.job,
            run_scheduled_for=timezone.make_aware(
                datetime(2026, 10, 23, 13, 55)),
            run_started_on=timezone.now())
        self.assertEqual(due_runs(datetime(2026, 10, 23, 14, 0), 10), {})

    def test_scheduled_but_not_started_run_still_runs(self):
        CronLog.objects.create(
            cron=self.job,
            run_scheduled_for=timezone.make_aware(
                datetime(2026, 10, 23, 13, 55)))
        self.assertEqual(
            due_runs(datetime(2026, 10, 23, 14, 0), 10),
            {'notify_missing_syllabi': '2026-10-23 13:55:00'})
