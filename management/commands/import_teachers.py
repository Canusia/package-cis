from django.core.management.base import BaseCommand
import os, csv, json, datetime

from cis.models.highschool import HighSchool
from cis.models.customuser import CustomUser
from cis.models.teacher import Teacher, TeacherHighSchool, TeacherCourseCertificate
from cis.models.course import Course
from cis.models.note import TeacherNote
from cis.utils import format_emplid

class Command(BaseCommand):
    '''
    DEPRECATED — do not use.

    This legacy CSV teacher importer has been phased out and is retained only
    for reference. Use the current importer instead:
    cis.services.importers.instructor_importer.InstructorImporter
    (schema: cis.services.importers.instructor_schema.InstructorRow), which is
    wired into the web UI and handles validation, whitespace stripping, and
    course/certificate assignment.
    '''
    help = '[DEPRECATED] Imports teachers from CSV file — use the instructor importer service instead'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')
        parser.add_argument(
            '--force', action='store_true',
            help='Run this deprecated command anyway (not recommended).'
        )

    def handle(self, *args, **kwargs):
        self.stderr.write(self.style.WARNING(
            'import_teachers is DEPRECATED and has been phased out. '
            'Use the instructor importer (cis.services.importers.instructor_importer) instead.'
        ))
        if not kwargs.get('force'):
            self.stderr.write(self.style.ERROR(
                'Aborting. Re-run with --force only if you understand this path is unsupported.'
            ))
            return

        path_to_file = kwargs['path']

        if True:
            from cis.utils import get_uploaded_file
            import io, csv

            uploaded_file = get_uploaded_file(path_to_file)
            
            reader = csv.DictReader(
                io.StringIO(
                    uploaded_file
                ), delimiter=','
            )

            row_num = 1
            for row in reader:
                print(f"Importing row # {row_num}")

                try:
                    # parse date of birth in mm/dd/yy format
                    row['date_of_birth'] = datetime.datetime.strptime(row['date_of_birth'], '%m/%d/%y')
                except:
                    row['date_of_birth'] = None

                row['hs_email'] = row['hs_email'].strip().lower()
                row['college_email'] = row['hs_email']
                
                if row['college_email'] == '':
                    row['college_email'] = row['teacher_id'] + '@setonhill.edu'
                if row['teacher_id'] == '':
                    row['teacher_id'] = row['college_email']
                
                username = row['college_email'].lower()
                teacher = Teacher.get_or_add(
                    psid=row.get('teacher_id'),
                    email=row['college_email'].lower(),
                    status=row.get('status', 'Active'),
                    username=row['college_email'].lower(),
                    first_name=row['first_name'],
                    last_name=row['last_name'],
                    middle_name=row.get('middle_name', ''),
                    secondary_email=row['hs_email'].lower(),
                    alt_email=row.get('home_email', ''),
                    primary_phone=row.get('cell_phone', '')
                )

                if not teacher:
                    print("Failed to create or retrieve teacher.")
                    print(row)
                    continue

                if row['date_of_birth']:
                    teacher.user.date_of_birth = row['date_of_birth']

                # teacher.user.psid = row.get('teacher_id')
                teacher.user.save()

                # print(teacher)
                try:
                    highschool = HighSchool.objects.get(
                        code=row['highschool_ceeb']
                    )

                    try:
                        if not TeacherHighSchool.objects.filter(
                            teacher=teacher,
                            highschool=highschool
                        ).exists():
                            teacher_highschool = TeacherHighSchool(
                                teacher=teacher,
                                highschool=highschool
                            )

                            teacher_highschool.save()
                        else:
                            teacher_highschool = TeacherHighSchool.objects.get(
                                teacher=teacher,
                                highschool=highschool
                            )

                        if row.get('course_name'):
                            row['course_name'] = row['course_name'].strip().replace('  ', ' ')

                            course = Course.objects.get(name=row['course_name'])

                            if not TeacherCourseCertificate.objects.filter(
                                teacher_highschool=teacher_highschool,
                                course=course,
                                status=row.get('Course_certificate_status', 'Teaching'),
                            ).exists():
                                teacher_course = TeacherCourseCertificate(
                                    teacher_highschool=teacher_highschool,
                                    course=course,
                                    highschool_course_name=row.get('F_CorrespondingHSCourse'),
                                    status=row.get('Course_certificate_status', 'Teaching')
                                )
                                
                                teacher_course.save()
                            else:
                                TeacherCourseCertificate.objects.filter(
                                    teacher_highschool=teacher_highschool,
                                    course=course,
                                    status=row.get('Course_certificate_status', 'Teaching'),
                                ).update(
                                    highschool_course_name=row.get('F_CorrespondingHSCourse')
                                )
                    except Exception as e:
                        print(e)
                        print(row)
                        
                    
                except HighSchool.DoesNotExist:
                    # print(row)
                    ...
                    
                except:
                    continue
                
                row_num += 1
