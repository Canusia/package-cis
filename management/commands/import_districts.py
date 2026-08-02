from django.core.management.base import BaseCommand
import os
import csv

from cis.models.district import District

class Command(BaseCommand):
    '''
    Imports District data from csv file
    '''
    help = 'Imports Districts from CSV file'

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
                    print(f"Importing row # {row_num}")
                    d = District(
                        name=row['name'],
                        address1=row['address1'],
                        address2=row['address2'],
                        city=row['city'],
                        state=row['state'],
                        postal_code=row['zip'],
                        temp_id=row['temp_id'],
                        status='Active'
                    )


                    d.save()
                    row_num += 1
