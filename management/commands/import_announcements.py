import os, csv, json
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

            with open(path_to_file, "r", encoding="utf-8-sig") as f:
                row_num = 0
                reader = csv.DictReader(f)
                for row in reader:
                    
                    print(row['title'])
                    print(row['description'])
                    print(row['excerpt'])
                    print(row['createdon'])
                    print(json.loads(row['visibility']))
                    print(json.loads(row['courses']))
                    row_num += 1
