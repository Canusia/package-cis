import os, csv
from datetime import datetime

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.student import Student

class Command(BaseCommand):
    '''
    Imports High School students data from csv file
    '''
    help = 'Imports high school student data from CSV file'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')

    def handle(self, *args, **kwargs):
        path_to_file = kwargs['path']

        if not os.path.isfile(path_to_file):
            print(f"Unable to find file at {path_to_file}")
        else:

            staff_group = Group.objects.get(name='ce')
            with open(path_to_file, "r", encoding="utf-8-sig") as f:
                row_num = 0
                reader = csv.DictReader(f)
                for row in reader:
                    
                    username = row['username'].lower()
                    user = CustomUser.get_or_add(
                        username=username,
                        email=row['email'].lower(),
                        first_name=row['firstname'],
                        last_name=row['lastname'],
                        is_staff=True,
                        is_active=True,
                        psid=row['id']
                    )
                    try:
                        user.groups.add(staff_group)
                    except Exception as e:
                        print(e)
                        print(f'Failed for {row["email"]}')
                        print(type(user))
                        print(user)
                    row_num += 1
