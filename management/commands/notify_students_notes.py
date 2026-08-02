from django.core.management.base import BaseCommand

from cis.models.student import Student

class Command(BaseCommand):
    help = 'Notify students who have a note attached in the last 24 hours'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        # Student.notify_student_notes(*args, **kwargs)
        Student.notify_counselor_student_notes(*args, **kwargs)