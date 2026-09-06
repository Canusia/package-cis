from django.conf import settings

from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.contrib.sites.models import Site

from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from mailer import send_mail, send_html_mail

from ..models.section import StudentRegistration, StudentDropRequest

from ..settings.registration_status_email import registration_status_email
# from ..settings.drop_wd_req_email import drop_wd_req_email

from cis.middleware import current_request

def _coreq_sections(section):
    """Every section co-req-linked to `section`, in both directions.

    `ClassSection.co_reqs` is `ManyToManyField('cis.ClassSection')`, not
    `ManyToManyField('self')`, so Django does not make it symmetrical: the row
    lives only on the lecture side. `lecture.co_reqs` returns the labs but
    `lab.co_reqs` is empty, so the relation is walked forwards for the labs and
    backwards for the lecture(s) — and on to those lectures' other labs, so a
    lecture with several labs is handled as one group.
    """
    from ..models.section import ClassSection

    sections = set(section.co_reqs.all())

    for parent in ClassSection.objects.filter(co_reqs=section):
        sections.add(parent)
        sections.update(parent.co_reqs.exclude(id=section.id))

    sections.discard(section)
    return sections


@receiver(post_delete, sender=StudentRegistration)
def remove_coreqs(sender, instance, **kwargs):
    """
    When a registration is deleted, also delete its co-req registrations.

    Symmetric in both directions: deleting the lecture removes its labs, and
    deleting a lab removes the lecture along with that lecture's other labs.

    Unlike the status path this cannot write with `.update()` to break the
    cycle — the rows have to be deleted so `student_transactions`' own
    post_delete receiver fires and clears each charge. Instead the whole co-req
    group is collected in one pass here and each row deleted individually with
    `_coreq_delete` set, so this receiver adds that row's note and then returns
    rather than walking back into the section it was called from.
    """
    cascaded = getattr(instance, '_coreq_delete', False)

    coreq_registrations = []
    if not cascaded:
        coreq_registrations = list(StudentRegistration.objects.filter(
            student=instance.student,
            class_section__in=_coreq_sections(instance.class_section)
        ))

    if cascaded:
        note = (f'Removed co-req registration for {instance.class_section} / '
                f'{instance.class_section.course} {instance.status}')
    elif coreq_registrations:
        note = (f'Removed registration and {len(coreq_registrations)} co-req '
                f'registration(s) for {instance.class_section} / '
                f'{instance.class_section.course} {instance.status}')
    else:
        note = (f'Removed registration for {instance.class_section} / '
                f'{instance.class_section.course} {instance.status}')

    instance.student.add_note(
        createdby=current_request().user if current_request() else None,
        note=note,
        meta={
            'type': 'public',
            'registration_id': str(instance.id)
        }
    )

    for registration in coreq_registrations:
        registration._coreq_delete = True
        registration.delete()

def _mirror_status(queryset, instance):
    """Copy `instance`'s status onto the co-req registrations in `queryset`.

    The write is a queryset .update(): raw SQL that fires no post_save, which
    is what stops the two propagation directions below recursing into each
    other. post_save is then re-sent by hand for each mirrored row, flagged
    with `_coreq_sync` so `update_registration` returns early rather than
    propagating again.

    The re-send matters because post_save on StudentRegistration is not only
    this receiver: `student_transactions.signals.manage_charges` creates and
    removes the registration's charge there. Without it a dropped lab keeps
    its lab fee even though its status followed the lecture to 'drop'.
    """
    mirrored_ids = list(queryset.values_list('id', flat=True))
    if not mirrored_ids:
        return

    queryset.update(
        status=instance.status,
        needs_mirroring=instance.needs_mirroring
    )

    for mirrored in StudentRegistration.objects.filter(id__in=mirrored_ids):
        mirrored._coreq_sync = True
        post_save.send(
            sender=StudentRegistration,
            instance=mirrored,
            created=False,
            raw=False,
            using=mirrored._state.db,
            update_fields=None
        )


@receiver(post_save, sender=StudentRegistration)
def update_registration(sender, instance, created, **kwargs):
    from datetime import datetime

    # This save is `_mirror_status` re-dispatching post_save for a row it just
    # mirrored. Propagating again from here would bounce the status back and
    # forth between the lecture and its labs.
    if getattr(instance, '_coreq_sync', False):
        return

    previous_status = instance.tracker.previous('status')
    status = instance.status

    coreqs = instance.class_section.co_reqs.all()
    if created:

        instance.student.add_note(
            createdby=current_request().user if current_request() else None,
            note=f'New registration for {instance.class_section}',
            meta={
                'type': 'public',
                'registration_id': str(instance.id)
            }
        )

        try:
            for coreq in coreqs:
                if not StudentRegistration.objects.filter(
                    student=instance.student,
                    class_section=coreq
                ).exists():
                    try:
                        reg = StudentRegistration(
                            student=instance.student,
                            class_section=coreq,
                            status=instance.status,
                            highschool=instance.highschool,
                            status_changed_on=dict()
                        )
                        reg.save()
                    except Exception as e:
                        print(e)
        except Exception as e:
            print(e)
    else:
        # Forward: this section is a lecture — push status to its co-reqs (labs).
        for coreq in coreqs:
            _mirror_status(
                StudentRegistration.objects.filter(
                    student=instance.student,
                    class_section=coreq
                ),
                instance
            )

        # Reverse: this section is a co-req (lab) — push status back to the
        # lecture(s) that list it, and on to those lectures' other co-reqs so a
        # lecture with several labs stays in step.
        #
        # `co_reqs` is a non-symmetrical M2M declared as
        # ManyToManyField('cis.ClassSection'), so `lab.co_reqs` is empty and the
        # relation has to be walked backwards explicitly. Every write goes
        # through `_mirror_status`, which is what stops this recursing.
        from ..models.section import ClassSection

        parents = ClassSection.objects.filter(co_reqs=instance.class_section)

        for parent in parents:
            _mirror_status(
                StudentRegistration.objects.filter(
                    student=instance.student,
                    class_section=parent
                ),
                instance
            )

            siblings = parent.co_reqs.exclude(id=instance.class_section.id)
            if siblings:
                _mirror_status(
                    StudentRegistration.objects.filter(
                        student=instance.student,
                        class_section__in=siblings
                    ),
                    instance
                )

    if previous_status != status:
        status_changed_on = instance.status_changed_on
        if not status_changed_on:
            status_changed_on = {}

        status_changed_on[status + "_on"] = datetime.now().strftime('%m/%d/%Y %I:%M:%S %p')
        instance.status_changed_on = status_changed_on

        try:
            instance.student.add_note(
                createdby=current_request().user if current_request() else None,
                note=f'Updating {instance.class_section} to {instance.sexy_status}',
                meta={
                    'type': 'public',
                    'registration_id': str(instance.id)
                }
            )
        except Exception as e:
            print(e)


        email_settings = registration_status_email.from_db()

        if status in email_settings.get('sis_mirror_trigger', []):
            StudentRegistration.objects.filter(
                pk=instance.id
            ).update(
                needs_mirroring=True
            )

@receiver(pre_save, sender=StudentRegistration)
def status_changed(sender, instance, **kwargs):
    """
    Registration status was updated, so update status_updated_on JSONField
    """
    from datetime import datetime

    previous_status = instance.tracker.previous('status')
    status = instance.status

    if previous_status != status:
        status_changed_on = instance.status_changed_on
        if not status_changed_on:
            status_changed_on = {}

        status_changed_on[status + "_on"] = datetime.now().strftime('%m/%d/%Y %I:%M:%S %p')
        instance.status_changed_on = status_changed_on

        email_settings = registration_status_email.from_db()
        if email_settings.get('is_active', 'No') == 'No':
            return


        trigger_list = email_settings.get('parent_trigger', [])
        try:
            if status in trigger_list:
                subject = email_settings.get('parent_email_subject')
                message = email_settings.get('parent_email')

                if subject:
                    message = Template(message)
                    context = Context({
                        'student_first_name': instance.student.user.first_name,
                        'student_email': instance.student.user.email,
                        'course_name': instance.class_section.course,
                        'highschool_name': instance.student.highschool.name if instance.student.highschool else '',
                        'highschool_code': instance.student.highschool.code if instance.student.highschool else '',
                        'course_title': instance.class_section.course.title,
                        'campus': instance.class_section.campus if instance.class_section.campus else '',
                        'registration_status': instance.get_status_display()
                    })

                    # add parent and school counselor
                    to = [instance.student.parent_email]
                    
                    text_body = message.render(context)

                    template = get_template('cis/email.html')
                    html_body = template.render({
                        'message': text_body
                    })
        
                    if getattr(settings, 'DEBUG', True):
                        to = ['kadaji@gmail.com']

                    send_html_mail(
                        subject,
                        text_body,
                        html_body,
                        settings.DEFAULT_FROM_EMAIL,
                        to
                    )
        except Exception as e:
            print(e)
            pass

        trigger_list = email_settings.get('student_trigger', [])
        if status in trigger_list:
            # send email
            subject, message = instance.get_email_template()
            
            if subject:
                message = Template(message)
                context = Context({
                    'student_first_name': instance.student.user.first_name,
                    'student_last_name': instance.student.user.last_name,
                    'highschool_name': instance.student.highschool.name if instance.student.highschool else '',
                    'highschool_code': instance.student.highschool.code if instance.student.highschool else '',
                    'student_email': instance.student.user.email,
                    'course_name': instance.class_section.course,
                    'course_title': instance.class_section.course.title,
                    'campus': instance.class_section.campus if instance.class_section.campus else '',
                    'status': instance.get_status_display()
                })
                to = [instance.student.user.email]

                text_body = message.render(context)

                template = get_template('cis/email.html')
                html_body = template.render({
                    'message': text_body
                })
    
                if getattr(settings, 'DEBUG', True):
                    to = ['kadaji@gmail.com']

                send_html_mail(
                    subject,
                    text_body,
                    html_body,
                    settings.DEFAULT_FROM_EMAIL,
                    to
                )
