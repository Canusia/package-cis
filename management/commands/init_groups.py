from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from django.conf import settings
from django.db.utils import IntegrityError

class Command(BaseCommand):
    '''
    Create groups in DB
    '''
    help = 'Creates user groups in DB'

    def handle(self, *args, **kwargs):
        groups = getattr(settings, "MY_CE")['roles']

        print("Found %d groups in settings" % len(groups))
        added = 0
    
        for group in groups.keys():
            try:
                g = Group(name=group)
                g.save()

                added += 1
            except IntegrityError:
                print(f"{group} exists...skipping")
        print(f"{added} group(s) were added")
