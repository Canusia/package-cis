"""Management commands and cron work that run per campus (MC-04, package-cis #28).

Not a command module: it lives beside commands/ so Django never tries to run it.

``CampusCommand`` is a BaseCommand that takes ``--campus <code>`` and runs
``handle()`` inside ``campus_context()``. The option is required in
multi-campus mode and optional otherwise, where the deployment's campus is
used, so existing single-campus invocations keep working unchanged.

``run_for_each_campus(name, work)`` is for cron: it calls ``work()`` once per
campus, each inside its own campus context, its own try/except (one campus
failing never stops the next) and its own Postgres advisory lock (a campus
whose previous run is still going is skipped rather than run twice). A
single-campus deployment runs it exactly once, as before.
"""
import hashlib
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from cis.campus_context import campus_context, deployment_campus, is_multi_campus

logger = logging.getLogger(__name__)


def _campus_by_code(code):
    from cis.models.course import Campus
    try:
        return Campus.objects.get(code=code)
    except Campus.DoesNotExist:
        raise CommandError(f'No campus with code {code!r}.')


class CampusCommand(BaseCommand):
    """BaseCommand that runs handle() for one campus.

    Subclasses that override add_arguments() must call super().
    """

    def add_arguments(self, parser):
        parser.add_argument(
            '--campus', default=None,
            help='Campus code to run for. Required when MULTI_CAMPUS is on.')

    def execute(self, *args, **options):
        code = options.get('campus')
        if code:
            campus = _campus_by_code(code)
        elif is_multi_campus():
            raise CommandError('--campus is required when MULTI_CAMPUS is on.')
        else:
            campus = deployment_campus()
        with campus_context(campus):
            return super().execute(*args, **options)


def _campuses():
    if not is_multi_campus():
        return [deployment_campus()]
    from cis.campus_gate import _prefixed_campuses
    return list(_prefixed_campuses().order_by('name'))


def _lock_key(name):
    # pg advisory locks take a signed 64-bit key.
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], 'big', signed=True)


def _try_lock(name):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [_lock_key(name)])
        return cursor.fetchone()[0]


def _unlock(name):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock(%s)', [_lock_key(name)])


def run_for_each_campus(name, work):
    """Call work() once per campus; returns the campuses it ran for."""
    ran = []
    for campus in _campuses():
        label = campus.code if campus is not None else 'no campus'
        lock_name = f'cis-cron:{name}:{campus.pk if campus is not None else "none"}'
        if not _try_lock(lock_name):
            logger.warning('[%s] %s is still running; skipped', label, name)
            continue
        try:
            with campus_context(campus):
                logger.info('[%s] %s', label, name)
                work()
            ran.append(campus)
        except Exception:
            logger.exception('[%s] %s failed', label, name)
        finally:
            _unlock(lock_name)
    return ran
