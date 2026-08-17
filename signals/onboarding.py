"""
Onboarding wiring for MyCE.

The tenant-specific step catalog (STEPS list, predicates, EVENT_TO_STEP_KEY)
lives in the tenant-config app and is resolved at ready() via
get_tenant_service('onboarding_steps'). This module owns only the wiring:
default-step seeding, event-bus handler registration, and the term-rollover
reseed receiver.

`user_logged_in` is Django's built-in signal, not part of our generic event
bus, so it stays as a normal @receiver below.
"""
import logging

from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from student_onboarding import handlers, events
from student_onboarding.api import (
    add_step, complete_step, get_or_create_for_current_term,
)
from student_onboarding.step_registry import register, all_steps, get as get_step

from cis.models.student import Student
from cis.services.tenant_services import get_tenant_service
from cis.utils import active_term

logger = logging.getLogger(__name__)


def _seed_default_steps(student, term=None):
    for step in all_steps():
        if step.seeded_when and not step.seeded_when(student, term):
            continue
        add_step(
            student,
            key=step.key,
            label=step.label,
            url_name=step.url_name,
            order=step.order,
            message=step.message,
            term=term,
        )


def on_application_started(student, **kwargs):
    _seed_default_steps(student)


def on_email_verified(student, **kwargs):
    """Phase two: the rest of the checklist appears once the account is
    verified.

    Registered alongside the completion handler for EMAIL_VERIFIED, so the
    verification step is marked done and the remaining steps are added in the
    same dispatch. Seeding is idempotent (`add_step` is unique on
    (onboarding, key)), so this is safe to run for an already-seeded student.
    """
    _seed_default_steps(student)


def _make_completion_handler(step_key):
    step = get_step(step_key)
    msg = step.complete_message if step else None
    def handler(student, **kwargs):
        complete_step(student, key=step_key, message=msg)
    handler.__name__ = f'on_{step_key}_completed'
    return handler


def register_handlers():
    steps_module = get_tenant_service('onboarding_steps')

    # Register step definitions with the student_onboarding registry.
    for step in steps_module.STEPS:
        register(step)

    # Wire event bus.
    handlers.register(events.APPLICATION_STARTED, on_application_started)
    for event_name, step_key in steps_module.EVENT_TO_STEP_KEY.items():
        handlers.register(event_name, _make_completion_handler(step_key))

    # Registered last: handlers run in registration order, so the
    # verification step is completed before the rest of the checklist is
    # seeded. Order is cosmetic today, but keeps the step list coherent for
    # anything reading it mid-dispatch.
    handlers.register(events.EMAIL_VERIFIED, on_email_verified)


@receiver(post_save, sender=Student,
          dispatch_uid='cis.onboarding.seed_on_student_created')
def seed_on_student_created(sender, instance, created, **kwargs):
    """Create and seed the onboarding record when the student record is
    created, rather than waiting for a first login.

    Every student-creation path goes through Model.save() - the signup form,
    the SIS importer, `_for_import_get_or_add`, the emplid path and the
    application form - so this one receiver covers them all. There is no
    Student.objects.bulk_create anywhere, which would bypass it.

    The CSV SIS importer sets `account_verified` before calling save(), so
    those students seed straight to phase two. The legacy
    `_for_import_get_or_add` path (`cis/models/student.py`) does not touch
    `account_verified` at all, so students created through it seed as
    unverified like a normal signup, and pick up phase two on their first
    login via `reseed_on_term_rollover` (or an explicit verification event).

    No-ops when there is no active term: StudentOnboarding.term is a non-null
    FK, so seeding blindly here would raise IntegrityError inside signup, SIS
    import and admin creation alike. The login receiver seeds later instead.

    Everything after the `created` / active-term guards is wrapped in a
    broad try/except: creating a Student must never fail because onboarding
    could not be seeded. A raising `seeded_when` predicate, a bad catalog
    entry, or any other unexpected error here degrades to "no onboarding
    seeded" rather than propagating out of Model.save() and taking down the
    signup form (which deletes the just-created CustomUser and re-raises) or
    the legacy SIS import path (which would otherwise commit the student row
    with no error surfaced at all).
    """
    if kwargs.get('raw'):
        return
    if not created:
        return
    term = active_term()
    if term is None:
        return
    try:
        get_or_create_for_current_term(instance, term=term)
        _seed_default_steps(instance, term=term)
    except Exception:
        logger.exception(
            'Failed to seed onboarding for newly created student %s',
            instance.pk,
        )


@receiver(user_logged_in, dispatch_uid='cis.onboarding.reseed_on_term_rollover')
def reseed_on_term_rollover(sender, request, user, **kwargs):
    """Create a fresh StudentOnboarding when the active term has advanced,
    and re-seed on every login.

    Re-seeding unconditionally (rather than only when the record has no steps)
    is what repairs verification that happened out of band. CE staff's "Mark
    as Verified" action is a `students.update(account_verified=True)` queryset
    update: it fires no post_save and dispatches no EMAIL_VERIFIED, so without
    this the student would stay stuck on phase one forever. `add_step` is
    idempotent, so the cost is one query on an already-seeded record.

    Also completes the `verify_email` step when the student is verified.
    Neither the queryset-update "Mark as Verified" path nor the legacy SIS
    importer ever dispatches EMAIL_VERIFIED, so without this the step (and
    therefore the parent StudentOnboarding row) never completes, leaving the
    student stuck in `notify_pending_onboarding`'s queryset forever nagging
    them to verify an account staff already verified. `complete_step` is a
    documented no-op when the step doesn't exist for the current term, so
    this is safe to call unconditionally.
    """
    student = Student.objects.filter(user=user).first()
    if student is None:
        return
    term = active_term()
    if term is None:
        return
    get_or_create_for_current_term(student, term=term)
    _seed_default_steps(student, term=term)
    if student.account_verified:
        complete_step(student, key='verify_email', term=term)
