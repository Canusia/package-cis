from django.core.management.base import BaseCommand
import os
import csv

from django.db.models import Q
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.customuser import CustomUser
from cis.models.course import Course, Cohort
from cis.utils import format_emplid

class Command(BaseCommand):
    '''
    Imports teacher course data from csv file
    '''
    help = 'Imports teacher courses from CSV file'

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
                    # row['PSID'] = format_emplid(row['PSID'])

                    try:
                        ht = Teacher.objects.filter(user__psid=row['teacherid']).all()

                        if len(ht) != 1:
                            pass
                        else:
                            school = HighSchool.objects.filter(code=row['ceeb']).all()
                            if len(school) != 1:
                                print(f"***Unable to find high schoolid {row['ceeb']} ")
                            else:
                                # subject, cat_num, section = row['COURSE'].split('-')
                                subject = row['subject']
                                cat_num = row['class_number']
                                section = row['section_no']

                                course = Course.objects.filter(
                                    Q(catalog_number__icontains=cat_num) &
                                    Q(cohort__designator__icontains=subject)
                                    ).all()
                                if len(course) != 1:
                                    print(f"***Unable to find {subject} {cat_num}")
                                else:
                                    try:
                                        ht_hs = TeacherHighSchool(teacher=ht[0], highschool=school[0])
                                        ht_hs.save()
                                    except:
                                        ht_hs = TeacherHighSchool.objects.filter(
                                            teacher=ht[0].id, highschool=school[0].id
                                        )[0]
                                    try:
                                        ht_cert = TeacherCourseCertificate(
                                            teacher_highschool=ht_hs,
                                            course=course[0]
                                        )
                                        ht_cert.save()
                                    except:
                                        print("Certificate exists")
                                    # check if
                                    print(f"{ht[0].user.first_name} at {school[0].name} for {course[0].title}")
                    except ValueError:
                        print(row)
                    # find high school
                    # find teacher
                    # find course

                    row_num += 1
