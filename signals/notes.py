from django.conf import settings

from django.utils.safestring import mark_safe
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.contrib.sites.models import Site

from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from mailer import send_mail, send_html_mail

from cis.models.note import (
    ClassSectionNote, StudentNote, TeacherApplicationNote,
    TeacherNote
)
from cis.settings.notes_email import notes_email

from alerts.models import Alert

@receiver(post_save, sender=StudentNote)
def student_note_added(sender, instance, created, **kwargs):
    if created and instance.meta.get('type') == 'response':
        parent_note = StudentNote.objects.get(pk=instance.parent)

        alert = Alert()
        alert.alert_type = 'student_note_response'
        alert.recipient = parent_note.createdby

        link = str(parent_note.student.ce_url) + '#notes'
        alert.message = f'<a class="display_in_modal" href="{link}">New note added to {instance.student} by {instance.createdby}'
        alert.save()

    if created and 'to_parent' in instance.meta.get('type'):
        instance.send_to_parent()

    if created and 'to_student' in instance.meta.get('type'):
        instance.send_to_student()

    if created and 'sms_to_student' in instance.meta.get('type'):
        instance.send_as_sms()

@receiver(post_save, sender=TeacherNote)
def teacher_note_added(sender, instance, created, **kwargs):
    if not instance.meta:
        instance.meta = {}

    if created and instance.meta.get('type') == 'response':
        parent_note = TeacherNote.objects.get(pk=instance.parent)

        alert = Alert()
        alert.alert_type = 'teacher_note_response'
        alert.recipient = parent_note.createdby

        link = str(parent_note.student.ce_url) + '#notes'
        alert.message = f'<a class="display_in_modal" href="{link}">New note added to {instance.teacher} by {instance.createdby}'
        alert.save()

    if created and 'to_instructor' in instance.meta.get('type'):
        instance.send_as_email()

@receiver(post_save, sender=TeacherApplicationNote)
@receiver(post_save, sender=ClassSectionNote)
def created_new_class_section_note(sender, instance, created, **kwargs):
    """
    Send email to instructor when added as 'to_teacher'
    """
    if created and instance.meta.get('type') == 'response':
        if sender == TeacherApplicationNote:
            parent_id = instance.parent
            try:
                parent_note = TeacherApplicationNote.objects.get(
                    pk=parent_id
                )

                alert = Alert()
                alert.alert_type = 'si_app_note_response'
                alert.recipient = parent_note.createdby

                link = str(parent_note.teacher_application.ce_url) + '#notes'
                alert.message = f'<a class="display_in_modal" href="{link}">New note added by {instance.createdby}'
                alert.save()
            except:
                pass
                
    if created and instance.meta.get('type') == 'to_instructor':
        email_settings = notes_email.from_db()

        if email_settings.get('is_active', 'No') == 'No':
            return

        if sender == ClassSectionNote:
            email_template = Template(email_settings['class_section_note_to_instructor_email'])
            subject = email_settings.get('class_section_note_to_instructor_subject')
            to = [instance.class_section.teacher.user.email]

            context = Context({
                'note': instance.note,
                'instructor_first_name': instance.class_section.teacher.user.first_name,
                'instructor_last_name': instance.class_section.teacher.user.last_name
            })

        if sender == TeacherApplicationNote:
            email_template = Template(email_settings['teacherapplication_note_to_instructor_email'])
            subject = email_settings.get('teacherapplication_note_to_instructor_subject')
            to = [instance.teacher_application.user.email]

            context = Context({
                'note': instance.note,
                'instructor_first_name': instance.teacher_application.user.first_name,
                'instructor_last_name': instance.teacher_application.user.last_name,
                'reply_url': instance.teacher_reply_url
            })

        text_body = email_template.render(context)
        template = get_template('cis/email.html')

        html_body = template.render({
            'message': text_body
        })

        if getattr(settings, 'DEBUG', True):
            to = ['akadajis@syr.edu', 'kadaji@gmail.com']

        if email_settings.get('is_active') == 'Debug':
            to = ['avi@canusia.com']

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )