"""Legacy name; body now delegates to student_onboarding.

The CronTab entry still uses this command name so existing schedules keep
running. The real logic lives in `notify_pending_onboarding` in the
student_onboarding submodule.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Deprecated name — forwards to notify_pending_onboarding.'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Scheduled run time')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--student', type=str, default=None)

    def handle(self, *args, **opts):
        forwarded = {}
        if opts.get('time'):
            forwarded['time'] = opts['time']
        if opts.get('dry_run'):
            forwarded['dry_run'] = True
        if opts.get('student'):
            forwarded['student'] = opts['student']
        call_command('notify_pending_onboarding', **forwarded)
