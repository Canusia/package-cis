import os, csv
from datetime import datetime

from django.utils.timezone import make_aware
from django.core.management.base import BaseCommand

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.student import Student
from cis.models.section import StudentRegistration, ClassSection
from cis.models.highschool_administrator import HSAdministrator

class Command(BaseCommand):
    '''
    Imports registration data from csv file
    '''
    help = 'Imports registration data from CSV file'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')

    def handle(self, *args, **kwargs):
        path_to_file = kwargs['path']

        errors = []
        if not os.path.isfile(path_to_file):
            print(f"Unable to find file at {path_to_file}")
        else:
            missing_crn = []
            with open(path_to_file, "r", encoding="utf-8-sig") as f:
                row_num = 0
                reader = csv.DictReader(f)
                for row in reader:
                                        
                    print(f"Importing row # {row_num}")
                    row_num += 1
                    
                    try:
                        student = Student.objects.get(
                            pidm=row['studentid']
                        )
                    except Student.DoesNotExist:
                        print(f'Student not found {row["studentid"]}')
                        continue

                    try:
                        highschool = HighSchool.objects.get(
                            name=row['highschool']
                        )
                    except HighSchool.DoesNotExist:
                        highschool = student.highschool
                        #print(f'High school not found {row["highschool"]}')
                        #continue

                    try:
                        class_section = ClassSection.objects.get(
                            class_number=row['crn'][0:6],
                            term__code=row['termcode']
                        )
                    except ClassSection.DoesNotExist:
                        # print(f'CRN does not exist {row["crn"]}')

                        try:
                            course = row['course'].split(', ')
                            cohort, catalog = course[0].split(' ')
                        except:
                            errors.append(row)
                            continue

                        # find new CRN
                        class_sections = ClassSection.objects.filter(
                            term__code=row['termcode'],
                            campus__code=row['campus'],
                            course__catalog_number=catalog,
                            course__cohort__designator=cohort
                        )

                        if not class_sections:
                            errors.append(row)

                            missing_crn.append(row['crn'])
                            
                            if row['status'] == 'add':
                                print(f'CRN does not exist {row["crn"]}')
                            continue
                        else:
                            class_section = class_sections[0]

                    status = row['status'].lower()
                    if status == 'add':
                        status = 'registered'
                    elif status == 'section is full':
                        status = 'section_is_full'
                    elif status == 'not approved':
                        status = 'not_approved'
                    elif status == 'withdraw':
                        status = 'withdrawn'
                    elif status == 'drop':
                        status = 'dropped'
                        
                    registration = StudentRegistration(
                        student=student,
                        class_section=class_section,
                        highschool=highschool,
                        status=status,
                        registration_type=row['type'].lower(),
                        status_changed_on={}
                    )

                    try:
                        registration.save()
                    except:
                        errors.append(row)
                        continue

                    registration.created_on = make_aware(datetime.strptime(row['appliedon'], '%Y-%m-%d %H:%M:%S'))
                    status_change = {}

                    if row['registeredon']:
                        status_change['registered_on'] = row['registeredon']

                    if row['approvedon']:
                        status_change['approved_on'] = datetime.strptime(
                            row['approvedon'], '%Y-%m-%d %H:%M:%S').date().strftime("%m/%d/%Y")
                        if row['approvedby']:
                            try:
                                hs_admin = HSAdministrator.objects.get(
                                    user__email=row['approvedby']
                                )
                                registration.reviewer = hs_admin
                            except HSAdministrator.DoesNotExist:
                                pass

                    if row['notapprovedon']:
                        status_change['notapproved_on'] = row['notapprovedon']
                        if row['notapprovedby']:
                            try:
                                hs_admin = HSAdministrator.objects.get(
                                    user__email=row['notapprovedby']
                                )
                                registration.reviewer = hs_admin
                            except:
                                pass

                    if row['droppedon']:
                        status_change['dropped_on'] = datetime.strptime(
                            row['droppedon'], '%Y-%m-%d %H:%M:%S').date().strftime("%m/%d/%Y")

                    if row['waitliston']:
                        status_change['waitlist_on'] = datetime.strptime(
                            row['waitliston'], '%Y-%m-%d %H:%M:%S').date().strftime("%m/%d/%Y")

                    if row['sectionisfullon']:
                        status_change['sectionisfull_on'] = datetime.strptime(
                            row['sectionisfullon'], '%Y-%m-%d %H:%M:%S').date().strftime("%m/%d/%Y")

                    registration.status_changed_on = status_change
                    try:
                        registration.save()
                    except:
                        errors.append(row)
                        pass

            print(set(missing_crn))
            print()
            print()
            print(len(errors))
            print()
            print(errors)
