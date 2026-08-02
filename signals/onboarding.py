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
from django.dispatch import receiver

from student_onboarding import handlers, events
from student_onboarding.api import (
    add_step, complete_step, get_or_create_for_current_term,
)
from student_onboarding.step_registry import register, all_steps, get as get_step

from cis.models.student import Student
from cis.services.tenant_services import get_tenant_service


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


@receiver(user_logged_in, dispatch_uid='cis.onboarding.reseed_on_term_rollover')
def reseed_on_term_rollover(sender, request, user, **kwargs):
    """If the active term has advanced since the student's latest onboarding,
    create a fresh StudentOnboarding for the new term and seed defaults."""
    student = Student.objects.filter(user=user).first()
    if student is None:
        return
    onboarding = get_or_create_for_current_term(student)
    if not onboarding.steps.exists():
        _seed_default_steps(student)
