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


def _seed_default_steps(student):
    for step in all_steps():
        if step.seeded_when and not step.seeded_when(student):
            continue
        add_step(
            student,
            key=step.key,
            label=step.label,
            url_name=step.url_name,
            order=step.order,
            message=step.message,
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

    No-ops when there is no active term: StudentOnboarding.term is a non-null
    FK, so seeding blindly here would raise IntegrityError inside signup, SIS
    import and admin creation alike. The login receiver seeds later instead.
    """
    if not created:
        return
    if active_term() is None:
        return
    get_or_create_for_current_term(instance)
    _seed_default_steps(instance)


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
    """
    student = Student.objects.filter(user=user).first()
    if student is None:
        return
    if active_term() is None:
        return
    get_or_create_for_current_term(student)
    _seed_default_steps(student)
