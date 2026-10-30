"""Onboarding recalculates after CE-side registration / SA / PC changes.

Before this, onboarding steps only moved forward, and only on events the
student portal dispatched. CE adding a class, dropping the only class, marking
the student agreement received or deleting it left the checklist wrong until
something else happened. `cis.signals.onboarding` now queues
`student_onboarding.api.recalculate` for the student on post_save / post_delete
of StudentRegistration, StudentAgreement and ParentConsent, once per student
per transaction, after commit.
"""
import datetime
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from django.test import TestCase

from student_onboarding.models import StudentOnboardingStep

from cis.campus_context import current_campus_or_none
from cis.models import CustomUser
from cis.models.course import Campus, Cohort, Course
from cis.models.highschool import HighSchool, HighSchoolCampus
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import ParentConsent, Student, StudentAgreement
from cis.models.term import AcademicYear, Term

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover - optional app
    _login_history_post_login = None

PREFIX = settings.CAMPUS_CODE_PREFIX
RECALC = 'student_onboarding.api.recalculate'


def _u(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


class _Base(TestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})

        ay = AcademicYear.objects.create(name=_u('AY'))
        self.term = Term.objects.create(academic_year=ay, code='F26', label=_u('Fall'))
        Setting.objects.update_or_create(
            key=f'{PREFIX}_cis_registrations',
            defaults={'value': {
                'active_term': str(self.term.id),
                'registration_terms': [str(self.term.id)],
            }})
        # Saving a ParentConsent sends a "consent received" email that reads
        # these keys.
        Setting.objects.update_or_create(
            key=f'{PREFIX}_regis_email',
            defaults={'value': {
                'is_active': 'No',
                'parent_consent_recv_subject': 'Consent received',
                'parent_consent_recv': 'Consent received.',
            }})

        self.hs = HighSchool.objects.create(name=_u('HS'), status='Active')
        campus = current_campus_or_none()
        if campus is not None:
            HighSchoolCampus.objects.create(
                highschool=self.hs, campus=campus, status='Active')
        course_campus = campus or Campus.objects.create(name=_u('Campus'))
        cohort = Cohort.objects.create(name=_u('Cohort'), designator='PC')
        self.course = Course.objects.create(
            catalog_number='101', title='Intro', name=_u('COURSE'),
            cohort=cohort, credit_hours=3, campus=course_campus)

        user = CustomUser.objects.create_user(
            username=_u('stu'), email=f'{_u("stu")}@example.com', password='x')
        # Verified: the tenant seeds `classes` / `student_agreement` only then.
        self.student = Student.objects.create(
            user=user, highschool=self.hs, grade_level='FR', account_verified=True)

        self.ce = CustomUser.objects.create_superuser(
            username=_u('ce'), email=f'{_u("ce")}@example.com', password='x')
        self.ce.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.client.force_login(self.ce)

    def _section(self):
        return ClassSection.objects.create(
            term=self.term, course=self.course, class_number=_u('CN'),
            section_number='01', highschool=self.hs)

    def _register(self, status='applied'):
        return StudentRegistration.objects.create(
            student=self.student, class_section=self._section(),
            highschool=self.hs, status=status, status_changed_on={})

    def _status(self, key):
        return StudentOnboardingStep.objects.get(
            onboarding__student=self.student, onboarding__term=self.term,
            key=key).status


class RecalculationTriggerTests(_Base):
    def test_seeded_fixture(self):
        self.assertEqual(self._status('classes'), 'pending')
        self.assertEqual(self._status('student_agreement'), 'pending')

    def test_ce_adds_class_completes_classes_step(self):
        section = self._section()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/ce/add_new_ajax/', {
                'model': 'studentregistration',
                'action': 'add_new_registration',
                'student': str(self.student.id),
                'term': str(self.term.id),
                'highschool': str(self.hs.id),
                'class_section': str(section.id),
                # Not 'applied': the view leaves status_changed_on unset, and
                # the pre_save receiver fills it only when the status differs
                # from the model default, so 'applied' hits the NOT NULL
                # constraint (pre-existing; reported separately).
                'status': 'approved',
            })
        self.assertEqual(response.json().get('status'), 'success', response.content)
        self.assertTrue(StudentRegistration.objects.filter(
            student=self.student, class_section=section).exists())
        self.assertEqual(self._status('classes'), 'completed')

    def test_ce_drop_reopens_classes_step(self):
        with self.captureOnCommitCallbacks(execute=True):
            registration = self._register()
        self.assertEqual(self._status('classes'), 'completed')

        with self.captureOnCommitCallbacks(execute=True):
            registration.status = 'dropped'
            registration.save()

        self.assertEqual(self._status('classes'), 'pending')

    def test_ce_waive_sa_completes_step(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get('/ce/student/ajax', {
                'action': 'mark_student_consent_recv',
                'id': str(self.student.id), 'term': str(self.term.id)})
        self.assertEqual(response.json()['status'], 'success', response.content)
        self.assertEqual(self._status('student_agreement'), 'completed')

    def test_ce_waive_sa_sends_the_signed_event(self):
        from student_onboarding import events as onboarding_events
        from student_onboarding.signals import onboarding_event
        seen = []

        def receive(sender, event=None, student=None, **kwargs):
            seen.append(event)

        onboarding_event.connect(receive)
        self.addCleanup(onboarding_event.disconnect, receive)
        self.client.get('/ce/student/ajax', {
            'action': 'mark_student_consent_recv',
            'id': str(self.student.id), 'term': str(self.term.id)})
        self.assertIn(onboarding_events.STUDENT_AGREEMENT_SIGNED, seen)

    def test_ce_delete_sa_reopens_step(self):
        with self.captureOnCommitCallbacks(execute=True):
            agreement = StudentAgreement.objects.create(
                student=self.student, term=self.term,
                student_signature='Signed',
                student_signed_on=datetime.datetime.now())
        self.assertEqual(self._status('student_agreement'), 'completed')

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get('/ce/student/ajax', {
                'action': 'delete_student_agreement',
                'record_id': str(agreement.id)})
        self.assertEqual(response.json()['status'], 'success', response.content)
        self.assertEqual(self._status('student_agreement'), 'pending')

    def test_ce_waive_pc_and_delete_pc_recalculate(self):
        # EWU ships the parent_consent step dormant, so assert the trigger.
        with patch(RECALC) as recalc:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.get('/ce/student/ajax', {
                    'action': 'waive_parent_consent',
                    'id': str(self.student.id), 'term': str(self.term.id)})
            self.assertEqual(response.json()['status'], 'success', response.content)
            self.assertEqual(recalc.call_count, 1)
            self.assertEqual(recalc.call_args.args[0].pk, self.student.pk)

            consent = ParentConsent.objects.get(student=self.student, term=self.term)
            recalc.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.get('/ce/student/ajax', {
                    'action': 'delete_parent_consent',
                    'record_id': str(consent.id)})
            self.assertEqual(response.json()['status'], 'success', response.content)
            self.assertEqual(recalc.call_count, 1)

    def test_bulk_status_change_recalculates_once_per_student(self):
        """The real CE bulk "Change Status" path, in autocommit (no
        ATOMIC_REQUESTS): the form wraps its loop in one transaction."""
        with patch(RECALC) as recalc:
            with self.captureOnCommitCallbacks(execute=True):
                registrations = [self._register() for _ in range(5)]
            recalc.reset_mock()

            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post('/ce/registration/bulk_actions', {
                    'action': 'change_status',
                    'new_status': 'dropped',
                    'registration_ids': [str(r.id) for r in registrations],
                })

        self.assertEqual(response.json().get('status'), 'success', response.content)
        self.assertEqual(
            StudentRegistration.objects.filter(
                student=self.student, status='dropped').count(), 5)
        self.assertEqual(recalc.call_count, 1)

    def test_bulk_status_change_saves_rows_in_one_form_transaction(self):
        """TestCase already wraps everything in atomic blocks, so the
        once-per-student count above would hold even if the form stopped
        batching. Prove the form opens its own transaction: every row save
        must run below one shared atomic block that the form opened (deeper
        than the test's), each in its own per-row savepoint."""
        from django.db import connection
        with patch(RECALC):
            with self.captureOnCommitCallbacks(execute=True):
                registrations = [self._register() for _ in range(3)]

        baseline = len(connection.atomic_blocks)
        stacks = []
        real_save = StudentRegistration.save

        def recording_save(instance, *args, **kwargs):
            stacks.append(list(connection.atomic_blocks))
            return real_save(instance, *args, **kwargs)

        with patch(RECALC), \
                patch.object(StudentRegistration, 'save', recording_save):
            response = self.client.post('/ce/registration/bulk_actions', {
                'action': 'change_status',
                'new_status': 'dropped',
                'registration_ids': [str(r.id) for r in registrations],
            })

        self.assertEqual(response.json().get('status'), 'success', response.content)
        self.assertEqual(len(stacks), 3)
        for stack in stacks:
            # The form's outer atomic + the per-row savepoint.
            self.assertGreaterEqual(len(stack), baseline + 2)
        outer = {id(stack[baseline]) for stack in stacks}
        self.assertEqual(len(outer), 1, 'rows were not saved in one shared transaction')
        rows = {id(stack[baseline + 1]) for stack in stacks}
        self.assertEqual(len(rows), 3, 'each row needs its own savepoint')

    def test_bulk_status_change_skips_a_failing_row(self):
        """Per-row savepoints: one row's DB error leaves the others saved."""
        from cis.forms.section import StudentRegistrationChangeStatusForm
        with patch(RECALC):
            with self.captureOnCommitCallbacks(execute=True):
                good, bad = self._register(), self._register()
        from django.http import QueryDict
        data = QueryDict(mutable=True)
        data.update({'action': 'change_status', 'new_status': 'dropped'})
        data.setlist('registration_ids', [str(bad.id), str(good.id)])
        form = StudentRegistrationChangeStatusForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        real_save = StudentRegistration.save

        def failing_save(instance, *args, **kwargs):
            if instance.pk == bad.pk:
                # A real DB error: it aborts the enclosing (sub)transaction.
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1/0')
            return real_save(instance, *args, **kwargs)

        with patch(RECALC), patch.object(StudentRegistration, 'save', failing_save):
            form.save()
        good.refresh_from_db()
        bad.refresh_from_db()
        self.assertEqual(good.status, 'dropped')
        self.assertEqual(bad.status, 'applied')

    def test_unrelated_registration_save_does_not_recalculate(self):
        with patch(RECALC) as recalc:
            with self.captureOnCommitCallbacks(execute=True):
                registration = self._register()
            recalc.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                registration = StudentRegistration.objects.get(pk=registration.pk)
                registration.grade = 'B'
                registration.save()
            recalc.assert_not_called()

            with self.captureOnCommitCallbacks(execute=True):
                registration.status = 'approved'
                registration.save()
            self.assertEqual(recalc.call_count, 1)

    def test_class_section_change_recalculates(self):
        with patch(RECALC) as recalc:
            with self.captureOnCommitCallbacks(execute=True):
                registration = self._register()
            recalc.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                registration = StudentRegistration.objects.get(pk=registration.pk)
                registration.class_section = self._section()
                registration.save()
            self.assertEqual(recalc.call_count, 1)

    def test_consent_notification_flag_save_does_not_recalculate(self):
        with patch(RECALC) as recalc:
            with self.captureOnCommitCallbacks(execute=True):
                agreement = StudentAgreement.objects.create(
                    student=self.student, term=self.term,
                    student_signature='Signed',
                    student_signed_on=datetime.datetime.now())
            self.assertEqual(recalc.call_count, 1)
            recalc.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                agreement.student_signature = 'Re-signed'
                agreement.save(update_fields=['student_signature'])
            recalc.assert_not_called()

    def test_rollback_does_not_recalculate(self):
        with patch(RECALC) as recalc:
            with self.captureOnCommitCallbacks(execute=True):
                try:
                    with transaction.atomic():
                        self._register()
                        raise RuntimeError('roll back')
                except RuntimeError:
                    pass
            recalc.assert_not_called()

            # A later change in the same outer transaction still recalculates.
            with self.captureOnCommitCallbacks(execute=True):
                self._register()
            self.assertEqual(recalc.call_count, 1)

    def test_recalculation_error_does_not_break_save(self):
        with patch(RECALC, side_effect=RuntimeError('boom')):
            with self.assertLogs('cis.signals.onboarding', level='ERROR'):
                with self.captureOnCommitCallbacks(execute=True):
                    registration = self._register()
        self.assertTrue(StudentRegistration.objects.filter(pk=registration.pk).exists())

    def test_registration_change_without_a_record_creates_none(self):
        # A past student (no onboarding for the active term) must not be
        # started on onboarding by a CE-side registration change.
        from student_onboarding.models import StudentOnboarding
        StudentOnboarding.objects.filter(student=self.student).delete()
        with self.captureOnCommitCallbacks(execute=True):
            self._register()
        self.assertFalse(StudentOnboarding.objects.filter(student=self.student).exists())

    def test_registration_change_with_a_record_recalculates(self):
        with patch(RECALC, return_value={}) as recalc:
            with self.captureOnCommitCallbacks(execute=True):
                self._register()
        recalc.assert_called_once()
        self.assertEqual(recalc.call_args.kwargs.get('term'), self.term)

    def test_multi_campus_skips_campus_terms_without_a_record(self):
        from student_onboarding.models import StudentOnboarding
        from cis.signals import onboarding as wiring
        other = Term.objects.create(
            academic_year=self.term.academic_year, code='S27', label=_u('Spring'))
        self.assertFalse(StudentOnboarding.objects.filter(
            student=self.student, term=other).exists())
        with patch.object(wiring, 'is_multi_campus', return_value=True), \
                patch.object(wiring, '_rollover_terms', return_value=[other, self.term]), \
                patch(RECALC, return_value={}) as recalc:
            wiring._recalculate_students({self.student.id})
        self.assertEqual([c.kwargs.get('term') for c in recalc.call_args_list], [self.term])

    def test_old_student_onboarding_without_recalculate_is_a_no_op(self):
        # package-cis must run against student_onboarding v0.0.20.
        with patch(RECALC, new=None):
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                self._register()
        self.assertEqual(callbacks, [])


class ShouldSeedCompatibilityTests(TestCase):
    """`_should_seed` defers to StepDefinition.should_seed, and falls back to
    the local arity handling for student_onboarding < v0.0.21."""

    def test_step_without_should_seed_uses_local_logic(self):
        from cis.signals.onboarding import _should_seed
        seen = []
        legacy = SimpleNamespace(
            key='legacy', seeded_when=lambda student: seen.append(student) or True)
        self.assertTrue(_should_seed(legacy, 'S', 'T'))
        self.assertEqual(seen, ['S'])
        self.assertTrue(_should_seed(SimpleNamespace(key='x', seeded_when=None), 'S', 'T'))

    def test_step_with_should_seed_delegates(self):
        from cis.signals.onboarding import _should_seed
        step = SimpleNamespace(key='new', seeded_when=None,
                               should_seed=lambda student, term: False)
        self.assertFalse(_should_seed(step, 'S', 'T'))
