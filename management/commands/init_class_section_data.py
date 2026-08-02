import datetime

from django.utils.crypto import get_random_string
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from django.conf import settings
from django.core.mail import send_mail
from django.db.utils import IntegrityError
from django.core.management import call_command
from django.contrib.sites.models import Site

from cis.models.term import AcademicYear, Term
from cis.models.customuser import CustomUser
from cis.models.course import Campus

from cis.middleware import current_request

class Command(BaseCommand):
    '''
    Create groups in DB
    '''
    help = 'Creates user groups in DB'

    def add_arguments(self, parser):
        ...
        # parser.add_argument('-d', '--domain', type=str, help='Fully qualified domain')
        # parser.add_argument('-p', '--password', type=str, help='Password for admin users')
        # parser.add_argument('-c', '--campus', type=str, help='Campus')

    def handle(self, *args, **kwargs):

        request = current_request()

        from cis.models.highschool import HighSchool
        from cis.models.course import Course, Cohort
        from cis.models.section import ClassSection

        from cis.models.teacher import Teacher, TeacherCourseCertificate, TeacherHighSchool

        if not HighSchool.objects.filter(
            name='HS1'
        ).exists():
            highschool = HighSchool(
                name='HS1',
                district=district,
                code='123',
                sau='123'
            )
            highschool.save()
        else:
            highschool = HighSchool.objects.get(
                name='HS1'
            )

        cohort = Cohort.get_or_add(
            'ACC', 'Accounting'
        )

        course = Course.get_or_add(
            catalog_number='100',
            title='Accounting 101',
            name='ACC 101',
            cohort=cohort,
            credit_hours='3.0'
        )

        print(course)

        teacher = Teacher.get_or_add(
            '12345678',
            'teacher@hs.edu',
            first_name='Teacher',
            last_name='LastName',
            username='teacher@hs.edu',
        )

        if not TeacherHighSchool.objects.filter(
            teacher=teacher,
            highschool=highschool
        ).exists():
            teacher_hs = TeacherHighSchool(
                teacher=teacher,
                highschool=highschool
            )

            teacher_hs.save()
        else:
            teacher_hs = TeacherHighSchool.objects.get(
                teacher=teacher,
                highschool=highschool
            )
        
        if not TeacherCourseCertificate.objects.filter(
            teacher_highschool=teacher_hs,
            course=course
        ).exists():
            teacher_cert = TeacherCourseCertificate(
                teacher_highschool=teacher_hs,
                course=course
            )
            teacher_cert.save()

        term = Term.objects.first()
        
        print(term)
        if not ClassSection.objects.filter(
            class_number='12345',
            term=term
        ).exists():
            class_section = ClassSection(
                teacher=teacher,
                highschool=highschool,
                course=course,
                class_number='12345',
                section_number='001',
                term=Term.objects.first()
            )
            class_section.save()
        else:
            print('123')
        
        if not ClassSection.objects.filter(
            class_number='45678',
            term=term
        ).exists():
            class_section = ClassSection(
                teacher=teacher,
                highschool=highschool,
                course=course,
                class_number='45678',
                section_number='002',
                term=Term.objects.first()
            )
            class_section.save()
