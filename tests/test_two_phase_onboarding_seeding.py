"""Onboarding is seeded in two phases, keyed on account verification.

An unverified student gets the verification step alone; the rest of the
checklist appears when EMAIL_VERIFIED fires. Records are created when the
Student row is created rather than on first login, so a student who never
signs in is still visible to notify_pending_onboarding.

The login receiver deliberately re-seeds every time: CE staff's "Mark as
Verified" action is a queryset update that fires no signal, so login is the
catch-up that repairs verification which happened out of band.
"""
import uuid

from django.contrib.auth.models import Group
from django.test import TestCase
from unittest.mock import patch

from student_onboarding import events as onboarding_events
from student_onboarding.models import StudentOnboarding
from student_onboarding.signals import onboarding_event

from cis.models.customuser import CustomUser
from cis.models.student import Student
from cis.models.term import AcademicYear, Term


def _term(code='TPO1'):
    ay = AcademicYear.objects.create(name=f'AY-{uuid.uuid4()}')
    return Term.objects.create(academic_year=ay, code=code, label=f'L-{code}')


def _user():
    return CustomUser.objects.create(
        username=f'u-{uuid.uuid4()}',
        email=f'{uuid.uuid4()}@example.com',
        first_name='Test', last_name='User', psid='-',
    )


class TwoPhaseSeedingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.term = _term()

    def setUp(self):
        # Every module that resolves the active term independently must be
        # patched, or the receiver silently no-ops on the None guard.
        for path in (
            'cis.signals.onboarding.active_term',
            'student_onboarding.student_onboarding.api.active_term',
            'myce_tenant_configs.services.onboarding_steps.active_term',
        ):
            p = patch(path, return_value=self.term)
            p.start()
            self.addCleanup(p.stop)

    def _keys(self, student):
        onboarding = StudentOnboarding.objects.get(
            student=student, term=self.term)
        return set(onboarding.steps.values_list('key', flat=True))

    def test_creating_an_unverified_student_seeds_verification_only(self):
        student = Student.objects.create(user=_user(), account_verified=False)
        self.assertEqual(self._keys(student), {'verify_email'})

    def test_creating_a_verified_student_seeds_the_full_checklist(self):
        student = Student.objects.create(user=_user(), account_verified=True)
        keys = self._keys(student)
        self.assertNotIn('verify_email', keys)
        self.assertIn('ferpa', keys)
        self.assertIn('classes', keys)

    def test_email_verified_event_adds_phase_two(self):
        student = Student.objects.create(user=_user(), account_verified=False)
        self.assertEqual(self._keys(student), {'verify_email'})

        student.account_verified = True
        student.save(update_fields=['account_verified'])
        onboarding_event.send(
            sender='tests', event=onboarding_events.EMAIL_VERIFIED,
            student=student,
        )

        keys = self._keys(student)
        self.assertIn('ferpa', keys)
        self.assertIn('classes', keys)
        self.assertIn('student_agreement', keys)

    def test_email_verified_also_completes_the_verification_step(self):
        # The pre-existing completion handler must still run alongside the
        # new seeding handler - both are registered for this event.
        student = Student.objects.create(user=_user(), account_verified=False)
        student.account_verified = True
        student.save(update_fields=['account_verified'])
        onboarding_event.send(
            sender='tests', event=onboarding_events.EMAIL_VERIFIED,
            student=student,
        )
        onboarding = StudentOnboarding.objects.get(
            student=student, term=self.term)
        step = onboarding.steps.get(key='verify_email')
        self.assertEqual(step.status, 'completed')

    def test_login_reseeds_after_out_of_band_verification(self):
        # Reproduces CE staff's "Mark as Verified", which is a queryset
        # update: no post_save, no EMAIL_VERIFIED. Login must repair it.
        from cis.signals.onboarding import reseed_on_term_rollover

        student = Student.objects.create(user=_user(), account_verified=False)
        self.assertEqual(self._keys(student), {'verify_email'})

        Student.objects.filter(pk=student.pk).update(account_verified=True)

        reseed_on_term_rollover(
            sender=None, request=None, user=student.user)

        self.assertIn('ferpa', self._keys(student))

    def test_login_completes_verify_email_after_staff_verification(self):
        # Staff's "Mark as Verified" fires no signal and completes nothing.
        # The login catch-up must both seed phase two AND complete the
        # verify_email step itself, or the row never leaves
        # notify_pending_onboarding's queryset.
        from cis.signals.onboarding import reseed_on_term_rollover

        student = Student.objects.create(user=_user(), account_verified=False)
        self.assertEqual(self._keys(student), {'verify_email'})

        Student.objects.filter(pk=student.pk).update(account_verified=True)
        student.refresh_from_db()

        reseed_on_term_rollover(
            sender=None, request=None, user=student.user)

        keys = self._keys(student)
        self.assertIn('ferpa', keys)

        onboarding = StudentOnboarding.objects.get(
            student=student, term=self.term)
        step = onboarding.steps.get(key='verify_email')
        self.assertEqual(step.status, 'completed')
        self.assertIsNotNone(step.completed_on)

    def test_seeding_is_idempotent(self):
        student = Student.objects.create(user=_user(), account_verified=True)
        before = self._keys(student)
        onboarding_event.send(
            sender='tests', event=onboarding_events.EMAIL_VERIFIED,
            student=student,
        )
        self.assertEqual(self._keys(student), before)
        onboarding = StudentOnboarding.objects.get(
            student=student, term=self.term)
        self.assertEqual(onboarding.steps.count(), len(before))


class NoActiveTermTests(TestCase):
    """Creating a student must never fail because onboarding cannot be seeded.

    The receiver runs inside signup, SIS import and admin creation alike, and
    StudentOnboarding.term is a non-null FK - an unguarded None would raise
    IntegrityError and take all three paths down together.
    """

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')

    def test_student_creation_succeeds_with_no_active_term(self):
        with patch('cis.signals.onboarding.active_term', return_value=None):
            student = Student.objects.create(user=_user())
        self.assertIsNotNone(student.pk)
        self.assertEqual(
            StudentOnboarding.objects.filter(student=student).count(), 0)


class SeedingErrorIsolationTests(TestCase):
    """A raising seeding step must never take down Student creation.

    Reproduces the failure mode from the review: anything besides
    `active_term() is None` propagating out of the receiver breaks
    `Model.save()`, and the signup path deletes the just-created CustomUser
    and re-raises while the legacy SIS path silently half-completes with the
    student row already committed and no error surfaced.
    """

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.term = _term(code='ERR1')

    def test_raising_seed_step_still_lets_student_creation_succeed(self):
        with patch('cis.signals.onboarding.active_term',
                    return_value=self.term), \
             patch('cis.signals.onboarding._seed_default_steps',
                   side_effect=RuntimeError('boom')):
            student = Student.objects.create(user=_user())
        self.assertIsNotNone(student.pk)


class SeededWhenArityTests(TestCase):
    """`seeded_when` predicates may take (student) or (student, term).

    v0.0.21 began passing `term` positionally, which raised TypeError on every
    tenant catalog still declaring `def _pred(student)` — and because
    `seed_on_student_created` wraps its body in try/except, the breakage
    degraded to "no onboarding seeded" instead of surfacing. `cis` adapts to
    whichever arity the tenant declares. See package-cis#7.
    """

    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')

    def _step(self, predicate, key='arity_probe'):
        from student_onboarding.step_registry import StepDefinition
        return StepDefinition(key=key, label='Probe', seeded_when=predicate)

    def test_one_arg_predicate_is_called_with_one_arg(self):
        from cis.signals.onboarding import _should_seed
        seen = []

        def legacy(student):
            seen.append(student)
            return True

        self.assertTrue(_should_seed(self._step(legacy), 'STUDENT', 'TERM'))
        self.assertEqual(seen, ['STUDENT'])

    def test_two_arg_predicate_receives_the_term(self):
        from cis.signals.onboarding import _should_seed
        seen = []

        def modern(student, term=None):
            seen.append((student, term))
            return True

        self.assertTrue(_should_seed(self._step(modern), 'STUDENT', 'TERM'))
        self.assertEqual(seen, [('STUDENT', 'TERM')])

    def test_one_arg_predicate_can_still_veto(self):
        from cis.signals.onboarding import _should_seed
        self.assertFalse(
            _should_seed(self._step(lambda student: False), 'S', 'T'))

    def test_varargs_predicate_is_given_the_term(self):
        from cis.signals.onboarding import _should_seed
        seen = []

        def flexible(*args):
            seen.append(args)
            return True

        self.assertTrue(_should_seed(self._step(flexible), 'S', 'T'))
        self.assertEqual(seen, [('S', 'T')])

    def test_no_predicate_always_seeds(self):
        from cis.signals.onboarding import _should_seed
        self.assertTrue(_should_seed(self._step(None), 'S', 'T'))

    def test_legacy_tenant_catalog_seeds_end_to_end(self):
        """The regression itself: a one-arg predicate must not silently
        disable seeding for a real student."""
        from unittest.mock import patch
        from student_onboarding.step_registry import (
            StepDefinition, register, _registry,
        )
        from student_onboarding.models import StudentOnboarding

        register(StepDefinition(
            key='legacy_arity', label='Legacy',
            seeded_when=lambda student: True,
        ))
        self.addCleanup(lambda: _registry.pop('legacy_arity', None))

        term = _term('ARITY1')
        with patch('cis.signals.onboarding.active_term', return_value=term):
            student = Student.objects.create(user=_user())

        onboarding = StudentOnboarding.objects.get(student=student, term=term)
        self.assertIn('legacy_arity',
                      set(onboarding.steps.values_list('key', flat=True)))
