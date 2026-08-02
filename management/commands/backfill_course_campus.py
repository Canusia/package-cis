"""Backfill the campus on academic years and courses for single-campus tenants.

Context: the SIS section importer now stamps each imported Course with the
campus on the term's academic year (`term.academic_year.campus`). For that to
take effect, academic years must actually carry a campus. On a single-campus
tenant every academic year and course belongs to the one campus, so this
command fills in any that are still NULL:

  1. academic years with campus IS NULL   -> the sole campus
  2. courses with campus IS NULL           -> the sole campus

Running the course backfill BEFORE the next import also prevents the
campus-scoped `get_or_create` lookup from creating duplicate campus-stamped
rows for legacy null-campus courses that lack a SIS GUID.

Safe by design:
  * Refuses to run unless exactly ONE campus exists (multi-campus tenants must
    assign campus deliberately, not by this blanket rule).
  * Idempotent — re-running touches nothing once everything has a campus.
  * `--dry-run` reports the counts without writing.
"""
from django.core.management.base import BaseCommand, CommandError

from cis.models.course import Campus, Course
from cis.models.term import AcademicYear


class Command(BaseCommand):
    help = (
        "Assign the sole campus to any academic years and courses that still "
        "have a NULL campus (single-campus tenants only)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        campuses = list(Campus.objects.all())
        if len(campuses) != 1:
            raise CommandError(
                f'Expected exactly one campus, found {len(campuses)}. '
                'Refusing to guess — assign campus deliberately on a '
                'multi-campus tenant.'
            )
        campus = campuses[0]

        ay_qs = AcademicYear.objects.filter(campus__isnull=True)
        courses = list(Course.objects.filter(campus__isnull=True))

        self.stdout.write(
            f'Sole campus: {campus} ({campus.id})\n'
            f'  academic years with NULL campus: {ay_qs.count()}\n'
            f'  courses with NULL campus:        {len(courses)}'
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('--dry-run: no changes written.'))
            return

        ay_updated = ay_qs.update(campus=campus)

        # A blanket UPDATE on courses would violate the
        # (cohort, catalog_number, campus) unique constraint wherever legacy
        # null-campus duplicates exist — they only coexist because NULL
        # campuses compare distinct. Stamp each course that lands on a free
        # slot; skip and report the rest so a human can dedup them. Management
        # commands run in autocommit, so each per-row update is visible to the
        # next clash check (this also catches already-stamped siblings).
        course_updated = 0
        skipped = []
        for course in courses:
            clash = Course.objects.filter(
                cohort_id=course.cohort_id,
                catalog_number=course.catalog_number,
                campus=campus,
            ).exists()
            if clash:
                skipped.append(course)
                continue
            Course.objects.filter(pk=course.pk).update(campus=campus)
            course_updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Backfilled campus on {ay_updated} academic year(s) and '
            f'{course_updated} course(s).'
        ))

        if skipped:
            self.stdout.write(self.style.WARNING(
                f'Skipped {len(skipped)} course(s) that would collide on '
                f'(cohort, catalog_number, campus) — dedup these manually:'
            ))
            for c in skipped:
                self.stdout.write(
                    f'  - id={c.id} cohort={c.cohort_id} '
                    f'catalog_number={c.catalog_number!r} name={c.name!r}'
                )
