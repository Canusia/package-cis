import os, csv
from datetime import datetime

from django.utils.timezone import make_aware
from django.core.management.base import BaseCommand

from cis.models.student import Student, StudentRecommendation
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
                    # if row['studentid'] != '51972':
                    #     continue

                    # print(row)
                    if row['status'] == 'started':
                        continue

                    try:
                        student = Student.objects.get(
                            pidm=row['studentid']
                        )
                    except Student.DoesNotExist:
                        print(row['studentid'])
                        continue

                    term = Term.objects.get(
                        code=row['termcode']
                    )

                    grade_level = ''
                    if row['grade_level'] == '12':
                        grade_level = 1
                    elif row['grade_level'] == '11':
                        grade_level = 2
                    elif row['grade_level'] == '10':
                        grade_level = 3
                    elif row['grade_level'] == '9':
                        grade_level = 4

                    permission = ''
                    if row['permission'] == 'yes':
                        permission = '1'
                    elif row['permission'] == 'no':
                        permission = '2'

                    rec = {}
                    rec['student_gpa'] = ''
                    rec['student_prereq'] = permission
                    rec['student_grade_level'] = str(grade_level)
                    rec['student_qualification'] = row['recommendation']

                    try:
                        recommendation = StudentRecommendation(
                            student=student,
                            term=term,
                            recommendation=rec
                        )
                        recommendation.save()
                    except Exception as e:
                        print(e)
                        print(f'Dup Recommendation {row["studentid"]}')
                    row_num += 1
