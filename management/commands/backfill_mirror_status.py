"""Backfill StudentRegistration.last_mirror_status from legacy 'SIS - Failed' notes."""
from django.core.management.base import BaseCommand
from django.utils import timezone

from cis.models.note import StudentNote
from cis.models.section import StudentRegistration


class Command(BaseCommand):
    help = (
        "Mark registrations as 'failed' if their last SIS-related student note "
        "is a failure note. Used once after deploying mirror_logs / "
        "last_mirror_status so existing failures show up on the triage page."
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        candidates = StudentRegistration.objects.filter(last_mirror_status__isnull=True)
        marked = 0

        for sr in candidates.iterator():
            last_note = (
                StudentNote.objects
                .filter(student=sr.student, note__startswith='SIS - ')
                .order_by('-createdon').first()
            )
            if not last_note:
                continue
            if 'Failed to process' not in last_note.note:
                continue

            marked += 1
            if not dry:
                sr.last_mirror_status = 'failed'
                sr.last_mirror_error  = last_note.note[:500]
                sr.last_mirror_at     = last_note.createdon or timezone.now()
                sr.save(update_fields=[
                    'last_mirror_status', 'last_mirror_error', 'last_mirror_at',
                ])

        verb = 'Would mark' if dry else 'Marked'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {marked} registration(s) as failed'
        ))
