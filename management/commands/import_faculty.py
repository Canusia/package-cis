"""Import faculty from a CSV file via the FacultyImporter service.

Usage: python manage.py import_faculty -p /path/to/faculty.csv
Writes <path>.results.csv with a RESULT column and prints a summary.
"""
import csv

from django.core.management.base import BaseCommand

from cis.models.faculty import FacultyCoordinator


class Command(BaseCommand):
    help = 'Import faculty (and course-admin role assignments) from a CSV file.'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', required=True, help='Path to the CSV file')

    def handle(self, *args, **options):
        path = options['path']
        try:
            fh = open(path, encoding='utf-8-sig')
        except FileNotFoundError:
            self.stderr.write(self.style.ERROR(f"File not found: {path}"))
            raise SystemExit(1)
        with fh:
            reader = csv.DictReader(fh)
            result = FacultyCoordinator.import_from_csv(reader)

        records = result.get('records', [])
        if records:
            fieldnames = list(records[0].keys())
            if 'RESULT' not in fieldnames:
                fieldnames.append('RESULT')
            out_path = path + '.results.csv'
            with open(out_path, 'w', newline='') as out:
                writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                for r in records:
                    writer.writerow(r)
            self.stdout.write(f"Results written to {out_path}")

        s = result.get('summary', {})
        self.stdout.write(self.style.SUCCESS(
            f"Faculty import: total={s.get('total', 0)} "
            f"successful={s.get('successful', 0)} failed={s.get('failed', 0)}"))
