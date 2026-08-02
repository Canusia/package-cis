import os, csv, json

from django.core.management.base import BaseCommand

from cis.models.district import District
from cis.models.highschool import HighSchool
from cis.models.customuser import CustomUser

from cis.models.note import HighSchoolNote
class Command(BaseCommand):
    '''
    DEPRECATED — do not use.

    This legacy CSV high school importer has been phased out and is retained
    only for reference. Use the current importer instead:
    cis.services.importers.highschool_importer.HighSchoolImporter
    (schema: cis.services.importers.highschool_schema.HighSchoolRow), which is
    wired into the web UI and handles validation and whitespace stripping.
    '''
    help = '[DEPRECATED] Imports high schools from CSV file — use the high school importer service instead'

    def add_arguments(self, parser):
        parser.add_argument('-p', '--path', type=str, help='Path to CSV data file')
        parser.add_argument(
            '--force', action='store_true',
            help='Run this deprecated command anyway (not recommended).'
        )

    def handle(self, *args, **kwargs):
        self.stderr.write(self.style.WARNING(
            'import_highschools is DEPRECATED and has been phased out. '
            'Use the high school importer (cis.services.importers.highschool_importer) instead.'
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
                
                print(f"Importing row # {row_num} " + row['HS_name'])

                if row.get('HS_name') == '':
                    continue
                
                try:
                    district = District.get_or_add(name=row['district_name'])
                except:
                    district = None

                # row['ceeb'] = row['id']
                # row['sau'] = row['id']
                
                highschool = HighSchool.get_or_add(
                    name=row['HS_name'],
                    code=row['ceeb'],
                    sau=row.get('sau', ''),
                    status=row.get('status', 'active').capitalize(),
                    address1=row['address_1'],
                    address2=row.get('address_2', ''),
                    city=row['city'],
                    state=row['state'],
                    postal_code=row['zip'],
                    primary_phone=row.get('phone', ''),
                    url=row.get('website', ''),
                    district=district
                )

                # Normalise to a tenant School Type code; the old 'Public'
                # default was never a valid value for this field.
                from cis.services.tenant_services import get_tenant_service
                hs_type_code = get_tenant_service('highschool_types').normalize(
                    row.get('School Type'))
                highschool.hs_type = [hs_type_code] if hs_type_code else []
                highschool.save()
                
                try:
                    notes = json.loads(row['notes'])
                    if notes:    
                        for note in notes:
                            comment_author = CustomUser.objects.get(email=note['comment_author_email'].lower())

                            note_obj = highschool.add_note(
                                createdby=comment_author,
                                note="Originally Added On - " + note['comment_date'] + "\r\n" + note['comment_content'],
                            )
                            note_obj.save()
                except:
                    ...

                print(f'Importing {row["HS_name"]}')
                row_num += 1
