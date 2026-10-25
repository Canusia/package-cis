from django.conf import settings

from django.db.models.signals import pre_save, post_save, m2m_changed, post_delete, pre_delete
from django.dispatch import receiver
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.contrib.sites.models import Site

from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from mailer import send_mail, send_html_mail

from ..models.section import (
    ClassSection,
    ClassSectionSyllabi
)
from ..models.term import Term

from cis.middleware import current_request

from ..settings.roster_verification import (
    roster_verification as roster_verification_settings
)

@receiver(post_delete, sender=ClassSectionSyllabi)
def syllabi_deleted(sender, instance, **kwargs):
    class_sections = instance.class_sections.all()

@receiver(m2m_changed, sender=ClassSectionSyllabi.class_sections.through)
def syllabi_added(sender, instance, action, reverse=False, pk_set=None, **kwargs):
    """A file added to a section puts that section back to pending review.

    Only the sections just added (``pk_set``), not every section the file
    already covers. Each is saved, not ``.update()``-d, so history keeps the
    previous review, and the old reviewer note is cleared (#127).
    """
    if action != 'post_add' or not pk_set:
        return
    # Fresh rows, so a caller's stale in-memory instance can't be saved over
    # newer data (reverse: section.classsectionsyllabi_set.add(file)).
    section_ids = [instance.pk] if reverse else pk_set
    sections = ClassSection.objects.filter(pk__in=section_ids)
    for section in sections:
        changed_on = section.syllabi_status_changed_on or {}
        if section.syllabi_status == 'pending review' and not changed_on.get('note'):
            continue
        section.syllabi_status = 'pending review'
        section.syllabi_status_changed_on = {}
        section.save()


@receiver(pre_delete, sender=ClassSectionSyllabi)
def reset_class_section_syl_status(sender, instance, **kwargs):

    class_sections = instance.class_sections.all()
    for section in class_sections:
        if not ClassSectionSyllabi.objects.filter(class_sections=section).exclude(
            id=instance.id
        ).exists():
            section.syllabi_status = ''
            # No file left: no review either (the report showed the old one).
            section.syllabi_status_changed_on = {}
            section.save()

@receiver(pre_save, sender=ClassSection)
def default_registration_term(sender, instance, **kwargs):
    """Derive the registration term when none is set.

    Registration happens against the term that *owns* the academic term: a
    child term -- a session or sub-term -- registers under its parent, and a
    term with no parent registers under itself.

    ``registration_term`` is nullable and plenty of sections only ever set
    ``term``. The charge signal in ``student_transactions`` writes
    ``class_section.registration_term`` into ``StudentTransaction.term``, which
    is NOT NULL, so applying for a class on such a section died with a
    NOT NULL violation that surfaced to the student as "You have already added
    it" -- a message about a completely different failure (ewu#53).

    A section that deliberately registers against some other term keeps it; the
    two fields exist separately for exactly that case. Only the immediate
    parent is used, not the root of the chain.
    """
    if instance.registration_term_id is not None or instance.term_id is None:
        return

    parent_id = Term.objects.filter(
        pk=instance.term_id
    ).values_list('parent_id', flat=True).first()

    instance.registration_term_id = parent_id or instance.term_id


@receiver(pre_save, sender=ClassSection)
def grades_submitted(sender, instance, **kwargs):
    """
    Grades Status was updated, so update status_updated_on JSONField
    """
    from datetime import datetime

    previous_status = instance.tracker.previous('grade_status')
    status = instance.grade_status

    if previous_status != status:
        status_changed_on = instance.grade_status_changed_on
        if not status_changed_on:
            status_changed_on = {}

        instance.grade_status_changed_on = status_changed_on
        status_changed_on[datetime.now().strftime('%m/%d/%Y %I:%M:%S %p')] = status

        # NOTE: the "grade_status == 'submitted'" instructor notification email that
        # used to live here now belongs to the optional ``grades`` app
        # (``grades/signals.py``). ``cis`` keeps only the timestamp bookkeeping on
        # its own field.

@receiver(pre_save, sender=ClassSection)
def roster_status_updated(sender, instance, **kwargs):
    """
    Notify when roster status is changed
    """
    from datetime import datetime

    previous_status = instance.tracker.previous('roster_status')
    current_status = instance.roster_status

    if not current_status:
        return

    if previous_status != current_status:

        # Set by the roster status form when an instructor or high school
        # admin reports through a portal; None for CE edits (#69).
        reporter = getattr(instance, '_roster_reported_by', None)

        # pending verification: ask whoever may verify (instructor and/or HS admins)
        if instance.roster_status == 'pending verification':
            instance.notify_roster_verifiers()
            if current_request():
                user = current_request().user
            else:
                user = None
            
            instance.add_note(
                user,
                'Changed roster status. Sent pending roster verification email'
            )
        
        # confirm the report to whoever made it
        if instance.roster_status in ['accurate', 'inaccurate']:
            instance.notify_teacher_on_roster_confirmed(reporter=reporter)

        # notify CE admins if status is in one of the selected status
        if instance.needs_ce_notificaton_on_roster_change():
            instance.notify_ce_staff_on_roster_change(reporter=reporter)
