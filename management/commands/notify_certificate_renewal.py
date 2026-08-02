import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from django.template import Context, Template
from django.template.loader import get_template

from mailer import send_html_mail

from cis.models.teacher import TeacherCourseCertificate
from cis.models.customuser import CustomUser
from cis.models.note import TeacherNote
from cis.settings.teacher_certificate_renewal import teacher_certificate_renewal


class Command(BaseCommand):
    help = 'Email instructors whose course certificates are due for renewal.'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        config = teacher_certificate_renewal.from_db()
        is_active = config.get('is_active', 'No')
        if is_active not in ('Yes', 'Debug'):
            return

        window_days = int(config.get('window_days', '90'))
        frequency = int(config.get('frequency', '7'))
        subject = config.get('email_subject', 'Credential Renewal Reminder')
        body_tpl = Template(config.get('email_message', ''))

        today = timezone.localdate()

        cron_user = CustomUser.objects.filter(username='cron').first()

        candidates = TeacherCourseCertificate.objects.select_related(
            'teacher_highschool__teacher__user',
            'teacher_highschool__highschool',
            'course',
        ).filter(
            teacher_highschool__teacher__status__iexact='active',
        )

        emails_sent = 0
        for cert in candidates.iterator():
            due = cert.renewal_due_date
            if not cert.is_expiring_within(window_days):
                continue

            last_sent = cert.last_reminder_sent_on
            if last_sent and (today - last_sent).days < frequency:
                continue

            user = cert.teacher_highschool.teacher.user
            context = Context({
                'teacher_first_name': user.first_name,
                'teacher_last_name': user.last_name,
                'course_name': cert.course.name,
                'highschool_name': cert.teacher_highschool.highschool.name,
                'renewal_due_date': due.strftime('%m/%d/%Y'),
                'expires_on': cert.expires_on.strftime('%m/%d/%Y') if cert.expires_on else '',
            })
            text_body = body_tpl.render(context)

            html_body = get_template('cis/email.html').render({'message': text_body})

            if getattr(settings, 'DEBUG', True) or is_active == 'Debug':
                to = ['kadaji@gmail.com']
            else:
                to = [user.email]

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to,
            )

            cert.last_reminder_sent_on = today
            cert.save(update_fields=['last_reminder_sent_on'])

            if cron_user:
                TeacherNote(
                    teacher=cert.teacher_highschool.teacher,
                    note=f'Sent credential renewal reminder for {cert.course.name} (due {due.strftime("%m/%d/%Y")}).',
                    createdby=cron_user,
                    meta={'type': ['private']},
                ).save()

            emails_sent += 1

        self.stdout.write(self.style.SUCCESS(f'Renewal reminders sent: {emails_sent}'))
