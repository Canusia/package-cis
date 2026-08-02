"""
Management command to geocode existing high schools.

Usage:
    python manage.py geocode_highschools
    python manage.py geocode_highschools --force  # Re-geocode all schools
"""
from django.core.management.base import BaseCommand
from cis.models.highschool import HighSchool


class Command(BaseCommand):
    help = 'Geocode high school addresses to get latitude/longitude coordinates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-geocode all schools, even those with existing coordinates',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)

        if force:
            schools = HighSchool.objects.exclude(address1='').exclude(city='')
            self.stdout.write('Geocoding all high schools with addresses...')
        else:
            schools = HighSchool.objects.filter(
                latitude__isnull=True
            ).exclude(address1='').exclude(city='')
            self.stdout.write('Geocoding high schools without coordinates...')

        total = schools.count()
        success = 0
        failed = 0

        for i, school in enumerate(schools, 1):
            self.stdout.write(f'[{i}/{total}] Geocoding: {school.name}... ', ending='')

            if school.geocode_address():
                school.save(update_fields=['latitude', 'longitude'])
                self.stdout.write(self.style.SUCCESS(f'OK ({school.latitude}, {school.longitude})'))
                success += 1
            else:
                self.stdout.write(self.style.WARNING('FAILED'))
                failed += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Geocoding complete: {success} succeeded, {failed} failed'))
