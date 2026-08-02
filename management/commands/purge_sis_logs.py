import logging
from django.core.management.base import BaseCommand
from cis.models.sis import SIS_Log

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Delete mailer log"

    def add_arguments(self, parser):
        parser.add_argument('days', type=int)

    def handle(self, *args, **options):
        days = options['days']

        count = SIS_Log.objects.purge_old_entries(days)
        logger.info("%s log entries deleted " % count)
