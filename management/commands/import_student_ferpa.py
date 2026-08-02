import os, csv
from datetime import datetime

from django.utils.timezone import make_aware
from django.core.management.base import BaseCommand

from cis.models.student import Student, StudentFerpa
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

                    permissions_granted = {}
                    permissions_granted['names'] = []
                    permissions_granted['code'] = []
                    ferpa = StudentFerpa(
                        student=student,
                        campus={}
                    )

                    if row['name1']:
                        permissions_granted['names'].append(row['name1'])
                        permissions_granted['code'].append(row['code1'])

                    if row['name2']:
                        permissions_granted['names'].append(row['name2'])
                        permissions_granted['code'].append(row['code2'])
                        
                    if row['name3']:
                        permissions_granted['names'].append(row['name3'])
                        permissions_granted['code'].append(row['code3'])
                    
                    if row['name4']:
                        permissions_granted['names'].append(row['name4'])
                        permissions_granted['code'].append(row['code4'])
                    
                    ferpa.permissions_granted = permissions_granted
                    ferpa.save()
                    row_num += 1
