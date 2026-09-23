"""Seed the DocumentType vocabulary and backfill the FKs that point at it.

Replaces two lists that never agreed and could not be made to:

  * what a course could require -- the hardcoded DOCUMENT_TYPES tuple in each
    tenant's myce_tenant_configs/services/course_document_types.py, editable
    only by a developer with a deploy;
  * what a student could upload -- the free-text lines in the CE-editable
    cis.settings.support_docs['types'] setting.

Seeds one copy per campus: neither source carries campus information, and each
campus owns its own vocabulary from here on.

This is a command rather than a data migration on purpose. A data migration
that trips over one tenant's dirty free text fails the whole deploy across
60+ databases; a command is re-runnable, inspectable, and can refuse to guess.

Safe by design:
  * Idempotent -- matches on (campus, code); re-running creates nothing.
  * `--dry-run` reports without writing.
  * Refuses to finish when any free-text value matches no known type, rather
    than dropping it or inventing a code for it. Silent half-success is how
    a requirements checklist can report every requirement unmet forever
    (Canusia/package-cis#43).

Backfill lookups are built as a single per-campus index up front rather than
calling `DocumentType.normalize()` per row -- `normalize()` loads every
DocumentType for a campus and compares in Python, so calling it once per row
would be a full table load per row. `normalize()` itself is unchanged and
still correct for its other (low-volume) callers.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cis.models.course import (
    Campus,
    CourseDocumentRequirement,
    DEFAULT_DOCUMENT_TYPES,
    DocumentType,
)
from cis.models.student import StudentSupportingDocument


class Command(BaseCommand):
    help = (
        'Seed the DocumentType vocabulary per campus from the tenant module '
        'and the support_docs setting, then backfill the document-type FKs.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing.')
        parser.add_argument(
            '--campus', default=None,
            help='Seed only the campus with this code (default: every campus).')

    def _source_vocabulary(self):
        """[(code, label)] from the tenant module, else the cis default."""
        from cis.services.tenant_services import get_tenant_override
        override = get_tenant_override('course_document_types', 'choices')
        if override is not None:
            return list(override())
        return list(DEFAULT_DOCUMENT_TYPES)

    def _setting_types(self):
        """The CE-entered free-text lines from support_docs['types']."""
        from cis.settings.support_docs import support_docs
        return list(support_docs.get_types())

    def _build_index(self, campus):
        """{casefolded code or label -> DocumentType} for one campus.

        Built once per campus so the backfills below resolve each row with a
        dict lookup instead of a fresh `DocumentType.normalize()` query (and
        full in-Python scan) per row.
        """
        index = {}
        for dt in DocumentType.objects.filter(campus=campus):
            index[dt.code.casefold()] = dt
            index[dt.label.casefold()] = dt
        return index

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        campus_code = options['campus']

        campuses = Campus.objects.all()
        if campus_code:
            campuses = campuses.filter(code=campus_code)
            if not campuses.exists():
                raise CommandError(f'No campus with code {campus_code!r}.')

        vocabulary = self._source_vocabulary()
        known = {code.casefold() for code, _ in vocabulary}
        known |= {label.casefold() for _, label in vocabulary}

        # Report unmatched setting values before writing anything.
        unmatched = [
            value for value in self._setting_types()
            if value.strip() and value.strip().casefold() not in known
        ]

        created = 0
        with transaction.atomic():
            for campus in campuses:
                for code, label in vocabulary:
                    exists = DocumentType.objects.filter(
                        campus=campus, code=code).exists()
                    if exists:
                        continue
                    created += 1
                    if not dry_run:
                        DocumentType.objects.create(
                            campus=campus, code=code, label=label)

            linked_reqs = 0 if dry_run else self._backfill_requirements()
            linked_docs = 0 if dry_run else self._backfill_uploads()

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            f'{"Would create" if dry_run else "Created"} {created} '
            f'document type(s) across {campuses.count()} campus(es).')
        if not dry_run:
            self.stdout.write(
                f'Linked {linked_reqs} course requirement(s) and '
                f'{linked_docs} uploaded document(s).')

        if unmatched:
            raise CommandError(
                'These support_docs types match no known document type and '
                'were not seeded — add them to the vocabulary or correct the '
                'setting, then re-run:\n  ' + '\n  '.join(sorted(unmatched)))

    def _backfill_requirements(self):
        """Link requirements to the type for their own course's campus."""
        linked = 0
        pending = (CourseDocumentRequirement.objects
                   .filter(document_type__isnull=True)
                   .select_related('course'))

        indexes = {}
        for req in pending:
            campus_id = req.course.campus_id
            if campus_id not in indexes:
                indexes[campus_id] = self._build_index(req.course.campus)
            index = indexes[campus_id]

            value = (req.document or '').strip()
            if not value:
                continue
            match = index.get(value.casefold())
            if match is None:
                continue
            req.document_type = match
            req.save(update_fields=['document_type'])
            linked += 1
        return linked

    def _backfill_uploads(self):
        """Link uploaded documents to the type for their own term's campus.

        StudentSupportingDocument carries no campus column of its own, but
        every row has a required `term`, and `term.academic_year.campus` is
        the same derivation `backfill_course_campus.py` documents the SIS
        importer using to stamp Course.campus. A row whose academic year has
        no campus assigned yet (a legitimate legacy state) falls back to the
        null-campus (unassigned) index. A row is NEVER matched against a
        *different* campus's vocabulary than its own -- a wrong-campus link
        is worse than no link -- so if the row's own campus has no match, it
        falls back to the null-campus index only, never another campus's.
        """
        linked = 0
        pending = (StudentSupportingDocument.objects
                   .filter(document_type_ref__isnull=True)
                   .exclude(document_type='')
                   .select_related('term__academic_year__campus'))

        indexes = {}
        unassigned_index = self._build_index(None)

        def _index_for(campus):
            if campus is None:
                return unassigned_index
            if campus.pk not in indexes:
                indexes[campus.pk] = self._build_index(campus)
            return indexes[campus.pk]

        for doc in pending:
            value = (doc.document_type or '').strip()
            if not value:
                continue
            folded = value.casefold()

            campus = doc.term.academic_year.campus
            match = _index_for(campus).get(folded)
            if match is None and campus is not None:
                match = unassigned_index.get(folded)
            if match is None:
                continue

            doc.document_type_ref = match
            doc.save(update_fields=['document_type_ref'])
            linked += 1
        return linked
