
import os, csv, logging, io

from django.core.management.base import BaseCommand

from cis.utils import get_uploaded_file

from cis.models.section import ClassSection, StudentRegistration
from cis.models.term import Term
from cis.models.settings import Setting
from cis.models.student import Student


logger = logging.getLogger(__name__)

class Command(BaseCommand):
    '''
    Imports data from SIS exported CSV files
    '''
    help = 'Import Class, Student and Registration Data from S3'

    def handle(self, *args, **kwargs):
        students = get_uploaded_file('student_export')

        if not students:
            logger.error('Unable to read student export')
        else:
            reader = csv.DictReader(io.StringIO(students))
            result = Student.import_from_csv(reader)

        # import class section data
        classes = get_uploaded_file('class_export')
        if not classes:
            logger.error('Unable to read classes export')
        else:
            reader = csv.DictReader(io.StringIO(classes))
            result = ClassSection.import_from_csv(reader)

        # Import registrations
        registrations = get_uploaded_file('registration_export')
        if not registrations:
            logger.error('Unable to read registration export')
        else:
            file_name = "registration_import_results.csv"

            #Reset registrations for the term
            reset_term_ids = Setting.get_value("cis_registrations", 'terms')
            reset_terms = Term.objects.filter(
                id__in=reset_term_ids
            )
            StudentRegistration.reset_registrations(reset_terms)

            reader = csv.DictReader(io.StringIO(registrations))
            result = StudentRegistration.import_from_csv(reader)
