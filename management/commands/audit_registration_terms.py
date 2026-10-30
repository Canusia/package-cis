"""Read-only audit for retiring ClassSection.registration_term.

A section has one term, and that term's parent stands in for the registration
term. Before relying on that, list what disagrees:

(a) sections whose registration_term is neither their term nor its parent,
    with how many registrations and charges they carry; and sections on a
    sub-term that bills with its parent whose registration_term is the
    sub-term itself (their old charges sit on the sub-term, but after the
    upgrade the sub-term bills with its parent);
(b) class_charge / school_charge transactions whose term is not the billing
    term of their registration's class section.

    python manage.py audit_registration_terms [--campus CODE]

Nothing is changed and the exit status is 0 either way.
"""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F

CHARGE_LABELS = ('class_charge', 'school_charge')
CHUNK = 1000


class Command(BaseCommand):
    help = ('Report sections and charges that disagree with the section-term '
            'tree (read-only).')

    def add_arguments(self, parser):
        parser.add_argument(
            '--campus', help='Campus code; limits the audit to its sections.')

    def handle(self, *args, **options):
        from cis.models.course import Campus
        from cis.models.section import ClassSection, StudentRegistration
        from student_transactions.models import StudentTransaction

        campus = None
        if options.get('campus'):
            try:
                campus = Campus.objects.get(code=options['campus'])
            except Campus.DoesNotExist:
                raise CommandError(f"No campus with code {options['campus']!r}.")

        sections = ClassSection.objects.all()
        if campus is not None:
            sections = sections.filter(course__campus=campus)

        # (a) registration_term outside {term, term.parent}
        mismatched = list(
            sections.exclude(registration_term__isnull=True)
            .exclude(registration_term=F('term'))
            .exclude(registration_term=F('term__parent'))
            .select_related('term', 'registration_term')
            .annotate(num_registrations=Count('studentregistration', distinct=True))
            .order_by('term__code', 'class_number'))
        own_sub_term = list(
            sections.filter(registration_term=F('term'),
                            term__parent__isnull=False,
                            term__bills_with_parent=True)
            .select_related('term__parent', 'registration_term')
            .annotate(num_registrations=Count('studentregistration', distinct=True))
            .order_by('term__code', 'class_number'))
        registration_section = {}
        for reg_id, section_id in StudentRegistration.objects.filter(
                class_section__in=[s.pk for s in mismatched + own_sub_term]
        ).values_list('pk', 'class_section_id'):
            registration_section[str(reg_id)] = section_id
        charges_by_section = Counter()
        if registration_section:
            for chunk in self._chunks(StudentTransaction.objects.filter(
                    label__in=CHARGE_LABELS, meta__registration__isnull=False
            ).values_list('meta', flat=True)):
                for meta in chunk:
                    section_id = registration_section.get(str(meta.get('registration')))
                    if section_id is not None:
                        charges_by_section[section_id] += 1

        self.stdout.write(
            f'(a) Sections whose registration_term is not their term or its '
            f'parent: {len(mismatched)}')
        for section in mismatched:
            self._write_section(section, charges_by_section)
        if mismatched:
            self.stdout.write(
                '  What to do: set term parents so each registration_term is '
                "its section's term or that term's parent, or move the "
                "charges to the section's billing term.")

        self.stdout.write(
            f'(a) Sections on a sub-term that bills with its parent whose '
            f'registration_term is the sub-term itself: {len(own_sub_term)}')
        for section in own_sub_term:
            self._write_section(section, charges_by_section)
        if own_sub_term:
            terms = sorted({s.term.code for s in own_sub_term})
            self.stdout.write(
                '  What to do: turn off "Bill with parent term" on '
                f'{", ".join(terms)} (their charges sit on those terms), or '
                'move the charges to the parent term.')

        # (b) charges outside their section's billing term
        in_scope = None
        if campus is not None:
            in_scope = set(sections.values_list('pk', flat=True))
        bad = []
        transactions = StudentTransaction.objects.filter(
            label__in=CHARGE_LABELS, meta__registration__isnull=False
        ).select_related('term').order_by('created_on')
        for chunk in self._chunks(transactions):
            ids = {str(t.meta.get('registration')) for t in chunk}
            registrations = {
                str(r.pk): r for r in StudentRegistration.objects.filter(pk__in=[
                    i for i in ids if self._is_uuid(i)]
                ).select_related('class_section__term__parent')}
            for transaction in chunk:
                registration = registrations.get(str(transaction.meta.get('registration')))
                if registration is None:
                    continue
                section = registration.class_section
                if in_scope is not None and section.pk not in in_scope:
                    continue
                if transaction.term_id != section.billing_term.pk:
                    bad.append((transaction, registration, section))

        self.stdout.write(
            f"(b) Charges whose term is not their section's billing term: {len(bad)}")
        for transaction, registration, section in bad:
            self.stdout.write(
                f'  transaction={transaction.pk} registration={registration.pk} '
                f'section={section.class_number} charge_term={transaction.term.code} '
                f'billing_term={section.billing_term.code} '
                f'amount={transaction.amount}')

    def _write_section(self, section, charges_by_section):
        self.stdout.write(
            f'  {section.class_number} {section.section_number} '
            f'term={section.term.code} registration_term='
            f'{section.registration_term.code} '
            f'registrations={section.num_registrations} '
            f'charges={charges_by_section[section.pk]}')

    @staticmethod
    def _is_uuid(value):
        import uuid
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError, TypeError):
            return False
        return True

    @staticmethod
    def _chunks(queryset):
        chunk = []
        for row in queryset.iterator(chunk_size=CHUNK):
            chunk.append(row)
            if len(chunk) >= CHUNK:
                yield chunk
                chunk = []
        if chunk:
            yield chunk
