"""send_registrations_to_sis must not run twice at once.

A run takes 20-25 minutes on a 30-minute schedule; an overlapping run would
mirror from a second stale snapshot of the queue (2026-10-08 incident)."""
from unittest.mock import patch

from django.core.management import call_command
from django.db import connections
from django.test import TransactionTestCase

from cis.management.commands.send_registrations_to_sis import RUN_LOCK_KEY
from cis.signals.crontab import cron_task_done

MODPATH = 'cis.management.commands.send_registrations_to_sis'


class SendRegistrationsToSisLockTests(TransactionTestCase):
    def setUp(self):
        from cis.models.settings import Setting
        from cis.settings.registration_status_email import registration_status_email
        Setting.objects.update_or_create(
            key=registration_status_email.key,
            defaults={'value': {'sis_mirror_trigger': ['registered']}})

    def _other_session(self):
        conn = connections.create_connection('default')
        self.addCleanup(conn.close)
        return conn

    def _try_lock(self, conn):
        # The same keys the command computes for the current campus.
        from cis.management.commands.send_registrations_to_sis import _run_lock_keys
        with conn.cursor() as cur:
            cur.execute('SELECT pg_try_advisory_lock(%s, %s)', _run_lock_keys())
            return cur.fetchone()[0]

    def test_second_run_skips_while_one_holds_the_lock(self):
        other = self._other_session()
        self.assertTrue(self._try_lock(other))      # a run is in progress
        summaries = []
        def done(sender, **kw):
            summaries.append(kw.get('summary'))
        cron_task_done.connect(done)
        self.addCleanup(cron_task_done.disconnect, done)

        with patch(f'{MODPATH}.StudentRegistration') as SR:
            call_command('send_registrations_to_sis', time='2026-10-08 21:41:00')
        SR.objects.pending_sis_mirror.assert_not_called()
        self.assertEqual(len(summaries), 1)
        self.assertIn('previous run still in progress', summaries[0])

    def test_lock_released_after_a_run(self):
        call_command('send_registrations_to_sis')
        self.assertTrue(self._try_lock(self._other_session()))

    def test_lock_released_when_the_run_raises(self):
        with patch(f'{MODPATH}.StudentRegistration') as SR:
            SR.objects.pending_sis_mirror.side_effect = RuntimeError('boom')
            with self.assertRaises(RuntimeError):
                call_command('send_registrations_to_sis')
        self.assertTrue(self._try_lock(self._other_session()))

    def test_lock_is_per_campus(self):
        """Multi-campus: the cron runs once per campus; one campus's long run
        must not make another campus's run skip."""
        from cis.management.commands.send_registrations_to_sis import campus_lock_key
        other = self._other_session()
        with other.cursor() as cur:   # campus "X" is mid-run
            cur.execute('SELECT pg_try_advisory_lock(%s, %s)',
                        [RUN_LOCK_KEY, campus_lock_key('some-other-campus-id')])
        from cis.models.section import StudentRegistration
        empty = StudentRegistration.objects.none()
        with patch(f'{MODPATH}.StudentRegistration') as SR:
            SR.objects.pending_sis_mirror.return_value = empty
            call_command('send_registrations_to_sis')
        SR.objects.pending_sis_mirror.assert_called_once()
