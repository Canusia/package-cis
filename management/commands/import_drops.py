import os, csv
from datetime import datetime

from django.utils.timezone import make_aware
from django.core.management.base import BaseCommand

from cis.models.student import Student
from cis.models.section import StudentDropRequest, StudentRegistration

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
                    if row['status'] == 'started':
                        continue

                    try:
                        student = Student.objects.get(
                            pidm=row['studentid']
                        )
                    except Student.DoesNotExist:
                        print(row['studentid'])
                        continue

                    try:
                        term = Term.objects.get(
                            code=row['term']
                        )
                    except:
                        pass

                    crn = row['crn'].replace(' (Lecture-Dual)', '')
                    crn = crn.replace(' (Lab-Dual', '')
                    crn = crn.replace(' (Dual)', '')
                    crn = crn.replace(' (Lecture-Bridge)', '')
                    crn = crn.replace(' (Lab-Bridge)', '')

                    try:
                        registration = StudentRegistration.objects.get(
                            class_section__term=term,
                            student=student,
                            class_section__class_number=crn
                        )
                    except:
                        print('Registration not found')
                        print(row['crn'] + ' ' + row['studentid'])
                        continue

                    req = StudentDropRequest(
                        student=student,
                        status=row['status'].lower().title(),
                        note=row['note'],
                        registration=registration
                    )
                    req.save()

                    row_num += 1
