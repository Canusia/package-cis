import re

from django.conf import settings

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.contrib.sites.models import Site

from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from mailer import send_mail, send_html_mail

from alerts.models import Alert

from ..models.customuser import CustomUser
from ..models.section import StudentDropRequest
from ..models.student import Student, ParentConsent

from cis.settings.registration_email import registration_email

@receiver(post_save, sender=ParentConsent)
def create_new_parentconsent(sender, instance, created, **kwargs):
    """
    Send confirmation email to student and parent when parent consent is
    added
    """
    if created:
        email_settings = registration_email.from_db()
        email_template = Template(email_settings['parent_consent_recv'])

        if email_settings.get('is_active', 'No') == 'No':
            return

        context = Context({
            'parent_name': instance.student.parent_first_name,
            'student_first_name': instance.student.user.first_name,
            'student_email': instance.student.user.email,
            'term': instance.term
        })
        text_body = email_template.render(context)
        to = [instance.student.user.email, instance.student.parent_email]

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        subject = email_settings.get('parent_consent_recv_subject')

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )

# @receiver(post_save, sender=StudentDropRequest)
# def alert_new_drop_request(sender, instance, created, **kwargs):
#     if created:      
#         # get EC admins from campus
#         campus = instance.registration.class_section.campus
        
#         staff_members = CustomUser.active_staff_at_campus(campus.id)
#         link = str(instance.ce_url)
#         for staff in staff_members:
#             alert = Alert()
#             alert.alert_type = 'student_drop_request'
#             alert.recipient = staff

#             alert.message = f'<a class="display_in_modal" href="{link}">New drop request submitted by {instance.registration.student}</a>'
#             alert.save()

# @receiver(post_save, sender=StudentDropRequest)
# def create_new_drop_request(sender, instance, created, **kwargs):
#     """
#     Send email when a drop request is created
#     """
#     if created:
#         email_settings = drop_wd_req_email.from_db()
#         email_template = Template(email_settings['submitted_email'])

#         if email_settings.get('is_active', 'No') == 'No':
#             return

#         context = Context({
#             'student_first_name': instance.student.user.first_name,
#             'student_last_name': instance.student.user.last_name,
#             'student_high_school': instance.student.highschool.name,
#             'course_name': instance.registration.class_section.course.cohort.designator + ' ' + instance.registration.class_section.course.catalog_number,
#             'course_title': instance.registration.class_section.course.title,
#             'class_number': instance.registration.class_section.class_number,
#             'term': str(instance.registration.class_section.term)
#         })
#         text_body = email_template.render(context)
    
#         # add student
#         to = [instance.student.user.email]

#         # add reviewer
#         if instance.registration.reviewer:
#             to.append(instance.registration.reviewer.user.email)

#         # get EC admins from campus
#         campus = instance.registration.class_section.campus
        
#         staff = CustomUser.active_staff_at_campus(campus.id)
#         if staff:
#             to += [user.email for user in staff]

#         if email_settings.get('is_active', 'No') == 'Debug':
#             to = ['kadaji@gmail.com']

#         template = get_template('cis/email.html')
#         html_body = template.render({
#             'message': text_body
#         })

#         subject = email_settings.get('submitted_email_subject')

#         send_html_mail(
#             subject,
#             text_body,
#             html_body,
#             settings.DEFAULT_FROM_EMAIL,
#             to
#         )

@receiver(post_save, sender=Student)
def created_new_student(sender, instance, created, **kwargs):
    """
    Send account verify request email when a student record is created
    """
    if created and instance.verification_id:
        email_settings = registration_email.from_db()

        if email_settings.get('is_active', 'No') == 'No':
            return

        instance.send_verification_request_email()

@receiver(pre_save, sender=CustomUser)
def student_id_updated(sender, instance, **kwargs):
    """
    When a SIS ID (psid) is assigned and matches id_verify_regex:
      - transition the related Student.application_status to 'accepted'
      - send the psid-assigned email (if enabled)
    """
    previous_psid = instance.tracker.previous('psid')
    psid = instance.psid

    if not (previous_psid == '-' and previous_psid != psid):
        return

    email_settings = registration_email.from_db()
    pattern = email_settings.get('id_verify_regex', r'^H\d{7}$')

    try:
        if not bool(re.match(pattern, str(psid))):
            return
    except Exception as e:
        print(e)
        return

    try:
        student = instance.student
    except Student.DoesNotExist:
        return

    if student and student.application_status != 'accepted':
        student.application_status = 'accepted'
        student.save(update_fields=['application_status'])
        try:
            student.add_note(None, 'SIS ID received; application accepted')
        except Exception as e:
            print(e)

    if email_settings.get('send_id_assigned_email', "No") == 'Yes' and student:
        try:
            student.send_psid_assigned_email()
        except Exception as e:
            print(e)


@receiver(pre_save, sender=Student)
def student_status_on_highschool(sender, instance, **kwargs):
    """
    When a highschool is assigned to a draft student, flip status to 'pending'.
    Covers both creation (highschool provided up front) and updates.
    """
    if not instance.highschool_id:
        return
    if instance.application_status != 'draft':
        return
    if instance._state.adding:
        instance.application_status = 'pending'
        return
    prev_hs = instance.tracker.previous('highschool_id')
    if prev_hs != instance.highschool_id:
        instance.application_status = 'pending'
