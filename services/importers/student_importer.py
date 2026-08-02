"""Two-phase student CSV importer: parse-into-batch, then commit selected rows.

Validation reuses StudentImportRowForm (and thus StudentProfileForm's field
validators). Created students reach the 'verified + pending' end-state with a
system-generated password; the verification email is suppressed by leaving
verification_id = None on the first save.
"""
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.db.models import Q

from cis.models.customuser import CustomUser
from cis.models.student import Student
from cis.models.highschool import HighSchool
from cis.models.student_import import StudentImportBatch, StudentImportRow
from cis.forms.student_import import StudentImportRowForm
from cis.services.importers.student_import_schema import StudentImportColumns
from cis.utils import active_term

logger = logging.getLogger(__name__)


class StudentImporter:
    def __init__(self, highschools=None, scope='ce'):
        self.allowed_highschools = (
            highschools if highschools is not None
            else HighSchool.objects.filter(status__iexact='Active')
        )
        self.scope = scope

    # ---- header validation -------------------------------------------------

    def header_errors(self, fieldnames):
        present = set(fieldnames or [])
        missing = [c for c in StudentImportColumns.required() if c not in present]
        return ['Missing required column: %s' % c for c in missing]

    # ---- phase 1: parse + classify ----------------------------------------

    @transaction.atomic
    def parse_into_batch(self, dict_reader, *, created_by, source_filename):
        batch = StudentImportBatch.objects.create(
            created_by=created_by, source_filename=source_filename or '',
            scope=self.scope, status='pending',
        )
        seen_emails = set()
        for index, raw in enumerate(dict_reader, start=1):
            row = {k: (v if v is not None else '') for k, v in raw.items()}
            status, errors = self._classify(row, seen_emails)
            StudentImportRow.objects.create(
                batch=batch, row_number=index, raw_data=row,
                status=status, errors=errors, selected=(status == 'valid'),
            )
        return batch

    def _classify(self, row, seen_emails):
        form = StudentImportRowForm(data=row, highschools=self.allowed_highschools)
        if not form.is_valid():
            return 'error', {k: [str(e) for e in v] for k, v in form.errors.items()}

        email = form.cleaned_data['email']
        if email in seen_emails or self._email_exists(email):
            return 'duplicate', {'email': ['A user with this email already exists.']}
        seen_emails.add(email)
        return 'valid', {}

    def _email_exists(self, email):
        return CustomUser.objects.filter(
            Q(email__iexact=email) | Q(username__iexact=email)
            | Q(secondary_email__iexact=email)
        ).exists()

    # ---- phase 2: commit ---------------------------------------------------

    def commit(self, batch, selected_row_ids):
        selected = {str(i) for i in selected_row_ids}
        created = skipped = failed = 0

        for row in batch.rows.all():
            if str(row.id) not in selected or row.status != 'valid':
                skipped += 1
                continue
            try:
                self._create_student(row.raw_data)
                row.result = 'Created'
                created += 1
            except Exception as exc:  # noqa: BLE001 - report per-row, keep going
                logger.error('Import row %s failed: %s', row.row_number, exc, exc_info=True)
                # result is CharField(max_length=255); keep a readable prefix and
                # never let a long error message crash the row.save() below.
                row.result = ('Failed: %s' % exc)[:255]
                failed += 1
            row.save(update_fields=['result'])

        batch.status = 'committed'
        batch.save(update_fields=['status'])
        return {'created': created, 'skipped': skipped, 'failed': failed}

    @transaction.atomic
    def _create_student(self, raw_data):
        form = StudentImportRowForm(data=raw_data, highschools=self.allowed_highschools)
        if not form.is_valid():
            raise ValueError('Row no longer valid: %s' % form.errors.as_json())

        data = form.cleaned_data
        email = data['email']

        user = CustomUser(username=email, email=email)
        user.set_password(get_random_string(20))
        user.save()

        term = active_term()
        student = Student(user=user)
        # End-state (b): verified + suppress verification email + pending.
        student.account_verified = True
        student.verification_id = None
        student.highschool = data['highschool']           # pre_save flips -> pending
        student.meta = {
            'ferpa_completed_for': [],
            'state_q_completed_for': [],
            'start_term': term.code if term else '',
        }
        student.save()  # Student.save() also adds the 'student' group

        # Reuse the profile form's metadata-driven persistence for every other
        # field (writes user/student/meta + profile_last_reviewed + grade_level).
        form.student = student
        form.save(student=student, commit=True)

        student.account_verified_on = timezone.now()
        student.save(update_fields=['account_verified_on'])

        self._seed_onboarding(student)
        return student

    def _seed_onboarding(self, student):
        try:
            from student_onboarding.signals import onboarding_event
            from student_onboarding import events as onboarding_events
            onboarding_event.send(
                sender=__name__,
                event=onboarding_events.APPLICATION_STARTED,
                student=student,
            )
        except Exception as exc:  # noqa: BLE001 - onboarding seeding is best-effort
            logger.warning('Onboarding seed failed for %s: %s', student.pk, exc)
