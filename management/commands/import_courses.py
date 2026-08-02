import os
from django.core.management.base import BaseCommand
import csv

from cis.models.course import (
    Course, Category, Department, College,
    Cohort, CourseUpload
)
from cis.models.term import AcademicYear, Term
from cis.models.highschool import HighSchool
from cis.models.section import SectionNumber

class Command(BaseCommand):
    '''
    Import course data from csv file
    '''
    help = 'Imports courses from CSV file'
 
    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')
        parser.add_argument('-m', '--model', type=str, help='Model name to import')


    def import_terms(self, file):
        path_to_file = file

        if True:
            from cis.utils import get_uploaded_file
            import io, csv

            uploaded_file = get_uploaded_file(path_to_file)
            
            reader = csv.DictReader(
                io.StringIO(
                    uploaded_file
                ), delimiter=','
            )

            for row in reader:
                acad_year = row['academic_year'].replace('&#8211;', '-')

                academic_year = AcademicYear.get_or_add(
                    name=acad_year
                )

                term = Term.get_or_add(
                    academic_year=academic_year,
                    label=row['name'],
                    code=row['code']
                )

                print(term)

    def import_academic_years(self, file):
        path_to_file = file

        if True:
            from cis.utils import get_uploaded_file
            import io, csv

            uploaded_file = get_uploaded_file(path_to_file)
            
            reader = csv.DictReader(
                io.StringIO(
                    uploaded_file
                ), delimiter=','
            )
            
            for row in reader:
                acad_year = row['academic_year'].replace('&#8211;', '-')

                academic_year = AcademicYear.get_or_add(
                    name=acad_year
                )

                print(academic_year)

    def import_category(self, file):
        path_to_file = file

        if True:
            from cis.utils import get_uploaded_file
            import io, csv

            uploaded_file = get_uploaded_file(path_to_file)
            
            reader = csv.DictReader(
                io.StringIO(
                    uploaded_file
                ), delimiter=','
            )
            
            for row in reader:
                c = Category(
                    name=row['name'],
                    temp_id=row['categoryid'])
                c.save()

                print(f"Imported {c.name}")

    def import_department(self, file):
        path_to_file = file

        if True:
            from cis.utils import get_uploaded_file
            import io, csv

            uploaded_file = get_uploaded_file(path_to_file)
            
            reader = csv.DictReader(
                io.StringIO(
                    uploaded_file
                ), delimiter=','
            )
            
            for row in reader:
                c = College.objects.get(temp_id=row['collegeid'])
                dept = Department(
                    name=row['name'],
                    college=c,
                    temp_id=row['departmentid']
                )
                dept.save()

                print(f"Imported {dept.name}")

    def import_cohort(self, file):
        path_to_file = file

        if True:
            from cis.utils import get_uploaded_file
            import io, csv

            uploaded_file = get_uploaded_file(path_to_file)
            
            reader = csv.DictReader(
                io.StringIO(
                    uploaded_file
                ), delimiter=','
            )
            
            for row in reader:
                subject, num = row['course_name'].split(' ')

                # subject = row['subject']
                cohort = Cohort.get_or_add(
                    subject,
                    subject
                )

                try:
                    cohort.save()
                    print(f"Imported {subject}")
                except Exception as e:
                    print(e)
                    return
                    print(f"Unable to import {subject}")

    def update_cohort(self, file):
        path_to_file = file

        if True:
            from cis.utils import get_uploaded_file
            import io, csv

            uploaded_file = get_uploaded_file(path_to_file)
            
            reader = csv.DictReader(
                io.StringIO(
                    uploaded_file
                ), delimiter=','
            )
            
            for row in reader:
                cat = Category.objects.get(temp_id=row['category'])
                print(cohort.name)
                
                cohort = Cohort.objects.get(temp_id=row['cohortid'])
                cohort.category=cat
                cohort.save()
                    
                print(f"Imported {cohort.name}")                

    def import_course(self, file):
        from cis.models.course import CourseAdministrator
        from cis.models.customuser import CustomUser

        path_to_file = file

        if True:
            from cis.utils import get_uploaded_file
            import io, csv

            uploaded_file = get_uploaded_file(path_to_file)
            
            reader = csv.DictReader(
                io.StringIO(
                    uploaded_file
                ), delimiter=','
            )
            
            for row in reader:
                row['name'] = row['name'].replace('  ', ' ')
                # continue
                subject, cat_num = row['name'].split(' ')
                subject = row['subject']
                
                course_title = row['title']
                name=row['name']

                credit_hours = row['credits']
                status = row.get('status', 'Active').capitalize()

                print(f"Importing {name}")
                try:
                    # cohort = Cohort.objects.get(designator=subject)
                    # get or create cohort
                    if len(subject) > 9:
                        subject = subject[0:9]
                    cohort, created = Cohort.objects.get_or_create(
                        designator=subject,
                        defaults={
                            'name': subject
                        }
                    )
                except Exception as e:
                    print(subject)
                    print(row)
                    print(e)
                    return

                dept = None
                
                meta = {
                    'available_for_si': row.get('isopen', True)
                }

                course = Course.add_or_update(
                    name=name,
                    catalog_number=cat_num,
                    cohort=cohort,
                    title=course_title,
                    credit_hours=credit_hours,
                    status=status,
                    meta=meta,
                    description=row.get('course_description', ''),
                    prereq=row.get('prereq', ''),
                    teacher_requirement=row.get('teacher_reqs', '')
                )

                # try:
                #     course_admin = CustomUser.objects.get(
                #         email=row['course_administrator']
                #     )

                #     admin = CourseAdministrator(
                #         course=course,
                #         user=course_admin,
                #         role='Administrator'
                #     )
                #     admin.save()
                # except:
                #     ...

                print(f"Imported {course.name}")                



                # try:
                #     files = json.loads(row['syllabi'])

                #     for file in files:
                #         file_name = '/Users/kadaji/Downloads/slcc/syllabus/' + file['subfolder'] + '/' + file['file_name']

                #         rec_file = CourseUpload(
                #             course=course
                #         )
                        
                #         f = File(open(file_name, 'rb'))

                #         rec_file.media.save(file['file_name'], f)
                #         rec_file.save()


                # except Exception as e:
                #     print(e)

    def import_college(self, file):
        with open(file, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                c = College(
                    name=row['name'],
                    temp_id=row['collegeid'])
                c.save()

                print(f"Imported {c.name}")

    def handle(self, *args, **kwargs):
        path_to_file = kwargs['path']
        model = kwargs['model']

        if model == 'category':
            self.import_category(path_to_file)
        elif model == 'college':
            self.import_college(path_to_file)
        elif model == 'department':
            self.import_department(path_to_file)
        elif model == 'cohort':
            self.import_cohort(path_to_file)
        elif model == 'course':
            self.import_course(path_to_file)
        elif model == 'section_numbers':
            self.import_section_numbers(path_to_file)
        elif model == 'term':
            self.import_terms(path_to_file)
        elif model == 'academic_year':
            self.import_academic_years(path_to_file)
