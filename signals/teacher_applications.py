import logging
from django.conf import settings

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.contrib.sites.models import Site

from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from mailer import send_mail, send_html_mail

from ..models.teacher_applicant import (
    TeacherApplication, ApplicantSchoolCourse,
    ApplicantRecommendation,
    ApplicantCourseReviewer
)

from cis.settings.teacher_application_email import (
    teacher_application_email as tapp_settings,
)

from cis.settings.inst_app_language import (
    inst_app_language as inst_app_page_settings
)

from alerts.models import Alert

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ApplicantCourseReviewer)
def assign_new_reviewer(sender, instance, created, **kwargs):
    """
    Send email to reviewer
    """
    if not created:
        # call notifications medthod
        instance.notify_status_change(instance.status)

@receiver(post_save, sender=ApplicantRecommendation)
def create_new_recommendation(sender, instance, created, **kwargs):
    """
    Send confirmation email to applicant when new recommendation has been created
    """
    if created:
        email_settings = inst_app_page_settings.from_db()
        email_template = Template(email_settings['rec_received_email_message'])

        context = Context({
            'teacher_first_name': instance.teacher_application.user.first_name,
            'teacher_last_name': instance.teacher_application.user.last_name,
            'email': instance.teacher_application.user.email,
            'recommender_name': instance.submitter.get('name'),
        })
        text_body = email_template.render(context)
        to = [instance.teacher_application.user.email]

        if instance.submitter.get('email'):
            to.append(
                instance.submitter.get('email')
            )
        
        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        subject = email_settings.get('rec_received_email_subject')

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )

@receiver(pre_save, sender=TeacherApplication)
# @receiver(pre_save, sender=ApplicantCourseReviewer)
def teacher_app_status_updated(sender, instance, **kwargs):
    from datetime import datetime

    previous_status = instance.tracker.previous('status')
    status = instance.status

    if previous_status != status:
        status_changed_on = instance.status_changed_on
        if not status_changed_on:
            status_changed_on = {}

        status_changed_on[datetime.now().strftime('%m/%d/%Y %I:%M:%S %p')] = status

        instance.status_changed_on = status_changed_on

        # call notifications medthod
        instance.notify_status_change(status)

        if previous_status == 'Submitted':
            # course admin changes this
            # get all alerts where type = new_si_application_submitted
            Alert.objects.filter(
                alert_type='new_si_application_submitted',
                read_on__isnull=True,
                message__contains=str(instance.id)
            ).update(
                read_on=datetime.now()
            )

        if previous_status == 'Approved for FC review':
            # course admin changes this
            # get all alerts where type = new_si_application_submitted
            Alert.objects.filter(
                alert_type='si_application_reviewed',
                read_on__isnull=True,
                message__contains=str(instance.id)
            ).update(
                read_on=datetime.now()
            )

@receiver(post_save, sender=TeacherApplication)
def create_new_application(sender, instance, created, **kwargs):
    """
    Send confirmation email to applicant when new application has been created
    """
    if created:
        email_settings = tapp_settings.from_db()
        email_template = Template(email_settings['new_applicant_email'])

        context = Context({
            'first_name': instance.user.first_name,
            'last_name': instance.user.last_name,
            'email': instance.user.email
        })
        text_body = email_template.render(context)
        to = [instance.user.email]

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        subject = email_settings.get('new_applicant_email_subject')

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )

# @receiver(post_save, sender=ApplicantSchoolCourse)
def selected_new_course(sender, instance, created, **kwargs):
    """
    Send confirmation email to applicant when new application has been created
    """
    if created:
        email_settings = tapp_settings.from_db()
        email_template = Template(email_settings['course_selected_email'])

        context = Context({
            'teacher_first_name': instance.teacherapplication.user.first_name,
            'teacher_last_name': instance.teacherapplication.user.last_name,
            'teacher_email': instance.teacherapplication.user.email,
            'application_url': instance.teacherapplication.ce_url,
            'course': instance.course,
            'highschool': instance.course
        })
        text_body = email_template.render(context)
        to = [email_settings.get('course_selected_email_recipient')]

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        if getattr(settings, 'DEBUG', True) or not to:
            to = ['kadaji@gmail.com']

        subject = email_settings.get('course_selected_email_subject')

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )
