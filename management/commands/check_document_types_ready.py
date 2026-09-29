"""Report whether this tenant is ready for DocumentType release 2 (#47).

#47 makes CourseDocumentRequirement.document_type required and drops the
legacy `document` / `document_type` string columns. On a tenant where
requirements or uploads are still unlinked, or courses have no campus to
scope a type to, that loses data. This command only reads and reports;
run init_document_types (and assign course campuses) to fix what it finds.

    python manage.py check_document_types_ready
    python manage.py check_document_types_ready --fail-if-not-ready   # for CI
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Read-only check of the DocumentType data #47 depends on.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fail-if-not-ready', action='store_true',
            help='Exit with an error when anything blocks #47.')

    def handle(self, *args, **options):
        from cis.models.course import Course, CourseDocumentRequirement, DocumentType
        from cis.models.student import StudentSupportingDocument

        counts = [
            ('document types', DocumentType.objects.count(), 'at least 1'),
            ('requirements without a document type',
             CourseDocumentRequirement.objects.filter(document_type__isnull=True).count(), '0'),
            ('uploads with a type name but no document type',
             StudentSupportingDocument.objects.filter(document_type_ref__isnull=True)
             .exclude(document_type='').count(), '0'),
            ('courses without a campus', Course.objects.filter(campus__isnull=True).count(), '0'),
            ('document types without a campus',
             DocumentType.objects.filter(campus__isnull=True).count(), '0'),
        ]

        blockers = []
        for label, value, wanted in counts:
            ok = value >= 1 if wanted == 'at least 1' else value == 0
            self.stdout.write(f'  {"ok " if ok else "!! "} {label}: {value} (want {wanted})')
            if not ok:
                blockers.append(label)

        if blockers:
            self.stdout.write(
                'NOT READY for #47. Run init_document_types and assign campuses '
                'to the courses and types listed above, then check again.')
            if options['fail_if_not_ready']:
                raise CommandError('Not ready for #47: ' + ', '.join(blockers))
        else:
            self.stdout.write('READY for #47.')
