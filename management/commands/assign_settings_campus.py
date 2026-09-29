"""Give a campus the campus-scoped settings rows (MC-05, package-cis #29).

Run once when a single-campus tenant turns MULTI_CAMPUS on: every existing
campus-scoped Setting row (CAMPUS_CODE_PREFIX-ed keys and the named ones in
cis.models.settings.EXTRA_CAMPUS_SCOPED_KEYS) still has campus NULL, and in
multi-campus mode those rows are no longer found. This assigns them to the
campus that has been using them. Global settings are left alone.

    python manage.py assign_settings_campus --campus EWU --dry-run
    python manage.py assign_settings_campus --campus EWU

The second campus's rows then come from register_settings / the settings
pages, run on that campus's host.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Assign the global campus-scoped Setting rows to one campus.'

    def add_arguments(self, parser):
        parser.add_argument('--campus', required=True, help='Campus code.')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from cis.models.course import Campus
        from cis.models.settings import Setting, is_campus_scoped

        try:
            campus = Campus.objects.get(code=options['campus'])
        except Campus.DoesNotExist:
            raise CommandError(f"No campus with code {options['campus']!r}.")

        rows = [row for row in Setting.objects.filter(campus__isnull=True)
                if is_campus_scoped(row.key)]
        for row in rows:
            self.stdout.write(f'  {row.key}')
        if options['dry_run']:
            self.stdout.write(f'{len(rows)} setting(s) would move to {campus.code}.')
            return
        Setting.objects.filter(pk__in=[row.pk for row in rows]).update(campus=campus)
        self.stdout.write(f'{len(rows)} setting(s) moved to {campus.code}.')
