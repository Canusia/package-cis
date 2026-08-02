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

@receiver(post_delete, sender=StudentRegistration)
def remove_coreqs(sender, instance, **kwargs):
    """
    When a registration is deleted, also delete any corequisites.
    """

    instance.student.add_note(
        createdby=current_request().user if current_request() else None,
        note=f'Removed registration and coreqs for {instance.class_section} / {instance.class_section.course} {instance.status}',
        meta={
            'type': 'public',
            'registration_id': str(instance.id)
        }
    )

    coreqs = instance.class_section.co_reqs.all()

    if coreqs:
        StudentRegistration.objects.filter(
            student=instance.student,
            class_section__in=coreqs
        ).delete()

@receiver(post_save, sender=StudentRegistration)
def update_registration(sender, instance, created, **kwargs):
    from datetime import datetime

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
        for coreq in coreqs:
            StudentRegistration.objects.filter(
                student=instance.student,
                class_section=coreq
            ).update(
                status=instance.status
            )

            StudentRegistration.objects.filter(
                student=instance.student,
                class_section=coreq
            ).update(
                needs_mirroring=instance.needs_mirroring
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
