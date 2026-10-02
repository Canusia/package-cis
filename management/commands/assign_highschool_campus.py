"""Link high schools to a campus (high school <-> campus links).

Run after migrating a multi-campus tenant, or when a school was created with
no campus context and so was not linked automatically. Create-only: schools
already linked to the campus are skipped and reported, never modified.

    python manage.py assign_highschool_campus --campus LAMAR --all --dry-run
    python manage.py assign_highschool_campus --campus LAMAR --all
    python manage.py assign_highschool_campus --campus LAMAR --ids <uuid> \
        --building-code B123 --status Active
"""
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction


class Command(BaseCommand):
    help = 'Link high schools to one campus, skipping ones already linked.'

    def add_arguments(self, parser):
        parser.add_argument('--campus', required=True, help='Campus code.')
        parser.add_argument('--all', action='store_true', help='Link every high school.')
        parser.add_argument('--ids', help='Comma-separated high school ids.')
        parser.add_argument(
            '--building-code', default='',
            help='Building code for the link. Only with a single --ids value.')
        parser.add_argument(
            '--status', default='Active', choices=['Active', 'Inactive'],
            help='Link status (default Active).')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        from cis.models.course import Campus
        from cis.models.highschool import HighSchool, HighSchoolCampus

        try:
            campus = Campus.objects.get(code=options['campus'])
        except Campus.DoesNotExist:
            raise CommandError(f"No campus with code {options['campus']!r}.")

        if bool(options['all']) == bool(options['ids']):
            raise CommandError('Give exactly one of --all or --ids.')

        code = (options['building_code'] or '').strip()
        if options['all']:
            if code:
                raise CommandError('--building-code needs exactly one --ids value.')
            schools = list(HighSchool.objects.order_by('name'))
        else:
            raw = [part.strip() for part in options['ids'].split(',') if part.strip()]
            if code and len(raw) != 1:
                raise CommandError('--building-code needs exactly one --ids value.')
            ids = []
            for part in raw:
                try:
                    ids.append(uuid.UUID(part))
                except ValueError:
                    raise CommandError(f'{part!r} is not a valid high school id.')
            found = {hs.pk: hs for hs in HighSchool.objects.filter(pk__in=ids)}
            missing = [str(i) for i in ids if i not in found]
            if missing:
                raise CommandError('No high school with id: ' + ', '.join(missing))
            schools = [found[i] for i in dict.fromkeys(ids)]

        linked_ids = set(HighSchoolCampus.objects.filter(campus=campus)
                         .values_list('highschool_id', flat=True))
        dry = options['dry_run']
        status = options['status']
        created = skipped = errors = 0

        for hs in schools:
            if hs.pk in linked_ids:
                skipped += 1
                self.stdout.write(f'  skipped {hs.name}: already linked to {campus.code}')
                continue
            if code:
                clash = (HighSchoolCampus.objects
                         .filter(campus=campus, building_code=code)
                         .select_related('highschool').first())
                if clash:
                    errors += 1
                    self.stdout.write(
                        f'  error {hs.name}: building code "{code}" is already used by '
                        f'{clash.highschool.name} at {campus.code}.')
                    continue
            if dry:
                created += 1
                self.stdout.write(f'  would link {hs.name}')
                continue
            try:
                with transaction.atomic():
                    HighSchoolCampus.objects.create(
                        highschool=hs, campus=campus, building_code=code, status=status)
            except IntegrityError:
                errors += 1
                self.stdout.write(
                    f'  error {hs.name}: could not link (building code or link '
                    f'already taken at {campus.code}).')
                continue
            created += 1
            self.stdout.write(f'  linked {hs.name}')

        verb = 'would be linked' if dry else 'linked'
        self.stdout.write(
            f'{created} school(s) {verb} to {campus.code}; '
            f'{skipped} skipped (already linked); {errors} error(s).')
