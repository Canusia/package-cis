"""MC-04 (#28): CampusCommand and per-campus cron fan-out.

CampusCommand adds --campus <code>: required in multi-campus mode, optional in
single-campus mode (where the deployment's campus is used), and the command's
handle() runs inside campus_context(). run_for_each_campus() runs a unit of
cron work once per campus, each inside its own context, try/except and lock,
and logs the campus it is working for.
"""
import uuid
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from cis.campus_context import current_campus_or_none
from cis.management.campus_command import CampusCommand, run_for_each_campus
from cis.models.course import Campus


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


class _Probe(CampusCommand):
    seen = []

    def handle(self, *args, **options):
        _Probe.seen.append(current_campus_or_none())


def _run(**options):
    _Probe.seen = []
    command = _Probe(stdout=StringIO(), stderr=StringIO())
    command.execute(**{'verbosity': 0, 'no_color': True, 'force_color': False,
                       'skip_checks': True, 'campus': None, **options})
    return _Probe.seen


class CampusCommandTests(TestCase):
    def setUp(self):
        Campus.objects.all().delete()
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')

    def test_single_campus_runs_as_the_deployment_campus(self):
        first = min((self.c1, self.c2), key=lambda c: c.name)
        self.assertEqual(_run(), [first])

    def test_campus_option_sets_the_context(self):
        self.assertEqual(_run(campus=self.c2.code), [self.c2])

    def test_unknown_campus_code_is_an_error(self):
        with self.assertRaises(CommandError):
            _run(campus='NOPE')

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_requires_campus(self):
        with self.assertRaises(CommandError):
            _run()
        self.assertEqual(_run(campus=self.c1.code), [self.c1])

    def test_context_is_restored_afterwards(self):
        _run(campus=self.c2.code)
        self.assertNotEqual(current_campus_or_none(), self.c2)

    def test_command_exposes_the_option(self):
        parser = _Probe().create_parser('manage.py', 'probe')
        self.assertIn('--campus', parser.format_help())


class RunForEachCampusTests(TestCase):
    def setUp(self):
        Campus.objects.all().delete()
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')

    def test_single_campus_runs_once(self):
        seen = []
        run_for_each_campus('probe', lambda: seen.append(current_campus_or_none()))
        self.assertEqual(len(seen), 1)

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_runs_once_per_campus_in_its_context(self):
        seen = []
        run_for_each_campus('probe', lambda: seen.append(current_campus_or_none()))
        self.assertEqual(sorted(c.pk for c in seen), sorted([self.c1.pk, self.c2.pk]))

    @override_settings(MULTI_CAMPUS=True)
    def test_one_campus_failing_does_not_stop_the_next(self):
        seen = []

        def work():
            campus = current_campus_or_none()
            if campus == self.c1:
                raise RuntimeError('boom')
            seen.append(campus)

        with self.assertLogs('cis.management.campus_command', level='ERROR') as logs:
            run_for_each_campus('probe', work)
        self.assertEqual(seen, [self.c2])
        self.assertIn(self.c1.code, ' '.join(logs.output))

    @override_settings(MULTI_CAMPUS=True)
    def test_a_campus_whose_lock_is_held_is_skipped(self):
        seen = []
        held = lambda name: name.endswith(str(self.c1.pk))
        with mock.patch('cis.management.campus_command._try_lock',
                        side_effect=lambda name: not held(name)), \
                mock.patch('cis.management.campus_command._unlock'):
            run_for_each_campus('probe', lambda: seen.append(current_campus_or_none()))
        self.assertEqual(seen, [self.c2])
