import os, csv
from datetime import datetime

from django.utils.timezone import make_aware
from django.core.management.base import BaseCommand

from cis.utils import format_emplid

from cis.models.customuser import CustomUser
from cis.models.course import Campus
from cis.models.highschool import HighSchool
from cis.models.student import Student, StudentCampusID

class Command(BaseCommand):
    '''
    Imports High School students data from csv file
    '''
    help = 'Imports high school student data from CSV file'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')

    def handle(self, *args, **kwargs):
        path_to_file = kwargs['path']

        campus = Campus.get_all()

        if not os.path.isfile(path_to_file):
            print(f"Unable to find file at {path_to_file}")
        else:
            with open(path_to_file, "r", encoding="utf-8-sig") as f:
                row_num = 0
                reader = csv.DictReader(f)
                for row in reader:
                    print(f"Importing row # {row_num}")
                    try:
                        highschool = HighSchool.objects.get(
                            name=row['High School']
                        )
                    except HighSchool.DoesNotExist:
                        print('Failed to find high school' + row['High School'])
                        highschool = HighSchool(
                            name=row['High School']
                        )
                        highschool.save()

                    if not row['Email']:
                        row['Email'] = row['TempID'] + '@email.com'

                    user = CustomUser.get_or_add(
                        username=row['Email'],
                        email=row['Email'],
                        first_name=row['FirstName'],
                        last_name=row['LastName'],
                        address1=row['Address'],
                        city=row['City'],
                        state=row['State'],
                        postal_code=row['Zip'],
                        primary_phone=row['CellPhone'],
                        date_of_birth=datetime.strptime(row['DoB'], '%Y-%m-%d').date()
                    )
                    user.created_at = make_aware(datetime.strptime(row['CreatedOn'], '%Y-%m-%d %H:%M:%S'))
                    user.save()

                    gender = ''
                    if row['Gender'] == 'Male':
                        gender = 'm'
                    elif row['Gender'] == 'Female':
                        gender = 'f'
                    elif row['Gender'] == 'Non-binary':
                        gender = 'non-binary'

                    hispanic = ''
                    if row['Hispanic'] == 'Yes':
                        hispanic = True
                    elif row['Hispanic'] == 'No':
                        hispanic = False

                    ethnicity = [ str(code) for code in row['RaceCode'].split(',')]
                    if len(row['GraduationYear']) > 4:
                        row['GraduationYear'] = row['GraduationYear'][2:]

                    if row['GraduationYear'] == '20H':
                        row['GraduationYear'] = '2020'
                        
                    student = Student._for_import_get_or_add(
                        pidm=row['TempID'],
                        user=user,
                        highschool=highschool,
                        middle_name=row['MiddleName'],
                        graduation_year=row['GraduationYear'],
                        state_id=row['State ID'],
                        gender=gender,
                        parent_first_name=row['ParentFirstName'],
                        parent_last_name=row['ParentLastName'],
                        parent_email=row['Parent Email'],
                        parent1_education_level=row['P1EdCode'],
                        parent2_education_level=row['P2EdCode'],
                        hispanic=hispanic,
                        ethnicity=ethnicity
                    )

                    if student:
                        if row['State ID']:
                            student.state_id = row['State ID']
                        
                        if row['EMPLID']:
                            for cm in campus:
                                stud_id = StudentCampusID(
                                student=student,
                                campus=cm,
                                user_id=format_emplid(row['EMPLID'])
                            )

                            if row['UnivEmail']:
                                stud_id.email = row['UnivEmail']
                            try:
                                stud_id.save()
                            except:
                                pass
                    else:
                        print(row)
                    row_num += 1
