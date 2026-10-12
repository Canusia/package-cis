from django.core.management.base import BaseCommand


class Command(BaseCommand):
    '''
    Daily jobs

    A placeholder: nothing is scheduled here. It used to run a leftover Ethos
    debug query (listing subjects, with no campus) and return; that was
    removed in package_ethos#4. Kept so any scheduler still calling it exits
    cleanly.
    '''
    help = 'Daily jobs (currently none)'

    def handle(self, *args, **kwargs):
        return
