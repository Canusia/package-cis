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
from collections import Counter

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

        Two passes on purpose: labels first, then codes, so a code always
        wins a collision with another type's label. A tenant with
        (code='hs_transcript', label='Transcript') and
        (code='transcript', label='HS Transcript') used to have the label
        pass run second and silently overwrite the code key -- every
        requirement with document='transcript' would backfill to the WRONG
        type. If a code still collides with a *different* type's label after
        that ordering, that's a genuine ambiguity in the vocabulary, and this
        refuses to guess (consistent with the settings-value refusal below)
        rather than pick one silently.
        """
        types = list(DocumentType.objects.filter(campus=campus))

        index = {}
        for dt in types:
            index[dt.label.casefold()] = dt
        for dt in types:
            key = dt.code.casefold()
            existing = index.get(key)
            if existing is not None and existing.pk != dt.pk:
                raise CommandError(
                    f'Ambiguous document type vocabulary on campus '
                    f'{campus!r}: type {dt.pk} (code={dt.code!r}) collides '
                    f'with type {existing.pk} (label={existing.label!r}) -- '
                    f'rename one of them and re-run.')
            index[key] = dt
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

            linked_reqs, skipped_reqs = (
                (0, Counter()) if dry_run else self._backfill_requirements())
            linked_docs, skipped_docs = (
                (0, Counter()) if dry_run else self._backfill_uploads())

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            f'{"Would create" if dry_run else "Created"} {created} '
            f'document type(s) across {campuses.count()} campus(es).')
        if not dry_run:
            self.stdout.write(
                f'Linked {linked_reqs} course requirement(s) and '
                f'{linked_docs} uploaded document(s).')
            # The docstring promises this command refuses to guess and never
            # half-succeeds silently -- that promise held for the settings
            # values below and was broken for the rows themselves: a tenant
            # with 5,000 requirements and 900 links used to see only
            # "Linked 900" with no hint that 4,100 were left unlinked.
            self._report_skips('course requirement(s)', skipped_reqs)
            self._report_skips('uploaded document(s)', skipped_docs)

        if unmatched:
            # A caller reading only the exit code can't tell whether *anything*
            # ran before this refusal. Say so explicitly when it did: seeding
            # and backfilling are real work already committed by the time this
            # raises, they just don't cover these particular free-text values.
            did_anything = not dry_run and (created or linked_reqs or linked_docs)
            lead = (
                'Valid types were seeded and links were made above; only '
                'these support_docs values match no known document type and '
                'were not seeded'
                if did_anything else
                'These support_docs types match no known document type and '
                'were not seeded')
            raise CommandError(
                f'{lead} — add them to the vocabulary or correct the '
                'setting, then re-run:\n  ' + '\n  '.join(sorted(unmatched)))

    def _report_skips(self, noun, skipped):
        if not skipped:
            return
        total = sum(skipped.values())
        breakdown = ', '.join(
            f'{count} {reason}' for reason, count in sorted(skipped.items()))
        self.stdout.write(f'Skipped {total} {noun}: {breakdown}.')

    def _backfill_requirements(self):
        """Link requirements to the type for their own course's campus.

        A campus-less course (`Course.campus` is nullable and historically
        unset -- see `backfill_course_campus.py`) falls back to the
        null-campus index, mirroring `_backfill_uploads` below. Before this,
        a campus-less course always built an empty index (this command only
        ever CREATES per-campus rows) and every one of its requirements was
        silently unbackfillable.
        """
        linked = 0
        skipped = Counter()
        pending = (CourseDocumentRequirement.objects
                   .filter(document_type__isnull=True)
                   .select_related('course__campus'))

        indexes = {}
        unassigned_index = self._build_index(None)

        def _index_for(campus):
            if campus is None:
                return unassigned_index
            if campus.pk not in indexes:
                indexes[campus.pk] = self._build_index(campus)
            return indexes[campus.pk]

        for req in pending:
            value = (req.document or '').strip()
            if not value:
                skipped['blank document value'] += 1
                continue
            folded = value.casefold()

            campus = req.course.campus
            match = _index_for(campus).get(folded)
            if match is None and campus is not None:
                match = unassigned_index.get(folded)
            if match is None:
                skipped['no matching type (campus-less course)'
                        if campus is None else 'no matching type'] += 1
                continue

            req.document_type = match
            req.save(update_fields=['document_type'])
            linked += 1
        return linked, skipped

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
        skipped = Counter()
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
                skipped['blank document_type value'] += 1
                continue
            folded = value.casefold()

            campus = doc.term.academic_year.campus
            match = _index_for(campus).get(folded)
            if match is None and campus is not None:
                match = unassigned_index.get(folded)
            if match is None:
                skipped['no matching type (campus-less term)'
                        if campus is None else 'no matching type'] += 1
                continue

            doc.document_type_ref = match
            doc.save(update_fields=['document_type_ref'])
            linked += 1
        return linked, skipped
