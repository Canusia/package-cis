
import csv, os, datetime, json

from django.core.files import File
from django.core.management.base import BaseCommand

from cis.models.term import AcademicYear
from cis.models.course import Course
from cis.models.section import ClassSection, ClassSectionSyllabi
from cis.models.teacher import Teacher
from cis.models.highschool import HighSchool
from cis.models.term import Term

class Command(BaseCommand):
    '''
    Imports work project data from csv file
    '''
    help = 'Imports class sections from CSV file'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        path_to_file = kwargs['path']
        from cis.utils import get_uploaded_file
        import io, csv

        uploaded_file = get_uploaded_file(path_to_file)

        if not uploaded_file:
            print(f"Unable to find file at {path_to_file}")
        else:

            reader = csv.DictReader(
                io.StringIO(
                    uploaded_file
                ), delimiter=','
            )

            result = ClassSection.import_from_csv(reader)
            print(result)