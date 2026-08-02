import os, csv

from django.core.management.base import BaseCommand

from cis.models.customuser import CustomUser
from cis.models.tech_center_staff import TechCenterStaff

class Command(BaseCommand):
    '''
    Imports Tech Center Staff data from csv file
    '''
    help = 'Imports Tech Center Staff data from CSV file'

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
                    username = row['user_email'].split('@')[0]

                    t_staff = TechCenterStaff.get_or_add(
                        username=username,
                        email=row['user_email'],
                        first_name=row['first_name'],
                        last_name=row['last_name']
                    )

                    print('Success')
                    row_num += 1
