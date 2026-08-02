import os, csv
from datetime import datetime

from django.utils.timezone import make_aware
from django.core.management.base import BaseCommand

from cis.models.student import Student, ParentConsent
from cis.models.term import Term

class Command(BaseCommand):
    '''
    Imports registration data from csv file
    '''
    help = 'Imports registration data from CSV file'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')

    def handle(self, *args, **kwargs):
        path_to_file = kwargs['path']

        if not os.path.isfile(path_to_file):
            print(f"Unable to find file at {path_to_file}")
        else:
            with open(path_to_file, "r", encoding="utf-8-sig") as f:
                row_num = 0
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        student = Student.objects.get(
                            pidm=row['studentid']
                        )
                    except Student.DoesNotExist:
                        print(row['studentid'])
                        continue

                    term = Term.objects.get(
                        code=row['term']
                    )

                    agreement = ParentConsent(
                        student=student,
                        term=term
                    )

                    try:
                        agreement.parent_signature = row['signature']
                        agreement.parent_signed_on = make_aware(
                            datetime.strptime(row['createdon'], '%Y-%m-%d %H:%M:%S')
                        )

                        agreement.save()
                    except:
                        print(f'Dup Agreement {row["studentid"]}')
                    row_num += 1
