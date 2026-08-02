import os, csv

from django.core.management.base import BaseCommand

from cis.models.district import District
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSPosition, HSAdministrator, HSAdministratorPosition
)
class Command(BaseCommand):
    '''
    DEPRECATED — do not use.

    This legacy CSV high school member (HS admin) importer has been phased out
    and is retained only for reference. Use the current importer instead:
    cis.services.importers.hs_member_importer.HSMemberImporter
    (schema: cis.services.importers.hs_member_schema.HSMemberRow), which is
    wired into the web UI and handles validation and whitespace stripping.
    '''
    help = '[DEPRECATED] Imports high school member data from CSV file — use the HS member importer service instead'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')
        parser.add_argument(
            '--force', action='store_true',
            help='Run this deprecated command anyway (not recommended).'
        )

    def handle(self, *args, **kwargs):
        self.stderr.write(self.style.WARNING(
            'import_hs_members is DEPRECATED and has been phased out. '
            'Use the HS member importer (cis.services.importers.hs_member_importer) instead.'
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
                
                email = row['email'].lower()
                if email == '':
                    continue

                hs_member = HSAdministrator.get_or_add(
                    email=email,
                    first_name=row['firstname'],
                    last_name=row['lastname'],
                    primary_phone=row.get('phone', ''),
                    fax=row.get('fax', ''),
                    middle_name=row.get('middlename', ''),
                    salutation=row.get('salutation', '')
                )

                row_num += 1

                try:
                    if row['ceeb'] == '':
                        continue
                    
                    ceebs = row.get('ceeb', '').split(',')
                    for ceeb in ceebs:
                        ceeb = ceeb.strip()
                        if ceeb == '':
                            continue
                        
                        highschool = HighSchool.objects.get(
                            code=ceeb
                        )
                    
                        hs_position = HSPosition.get_or_add(name=row.get('position_title', 'Primary Contact'))
                        
                        hsmember_position = HSAdministratorPosition.get_or_add(
                            hsadmin=hs_member,
                            highschool=highschool,
                            position=hs_position,
                            status=row.get('status', 'Active')
                        )

                    print('Success')
                except Exception as e:
                    print(e)
                    print(row)
                    # return

