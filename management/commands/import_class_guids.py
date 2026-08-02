import os, csv

from django.core.management.base import BaseCommand

from cis.models.district import District
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSPosition, HSAdministrator, HSAdministratorPosition
)
from cis.models.section import ClassSection

class Command(BaseCommand):
    '''
    Imports High School member data from csv file
    '''
    help = 'Imports high school member data from CSV file'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')

    def handle(self, *args, **kwargs):
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
                
                term_code = row['SSBSECT_TERM_CODE']
                crn = row['SSBSECT_CRN']
                guid = row['SSBSGID_GUID']

                section = ClassSection.objects.filter(
                    term__code=term_code,
                    class_number=crn
                )

                if section.exists():
                    meta = section[0].meta
                    if not meta:
                        meta = {}
                    meta['section_id'] = guid
                    
                    section.update(meta=meta)
                    
                    print(f'{row_num} Success')
                    
                row_num += 1
