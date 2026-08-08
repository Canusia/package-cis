"""Incomplete-application reminders.

`instructor_app` ships a command of this same name. Django's ``get_commands()``
iterates ``reversed(apps.get_app_configs())``, so the app listed *earlier* in
INSTALLED_APPS wins — which on a default tenant is `cis`, silently shadowing
instructor_app. The body below queries the legacy
``cis.models.teacher_applicant`` tables; on a tenant whose applications live in
instructor_app those are empty, so the cron ran green and sent nothing.

So when instructor_app is installed, hand this name to its implementation and
keep the legacy body only for tenants still on the legacy models. Deciding at
import time rather than by deleting this module means neither kind of tenant
goes silent, and an existing ``CronTab`` row keeps working under the same
command name either way.
"""
import importlib.util
from datetime import datetime
from importlib import import_module

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage, EmailMultiAlternatives

from django.contrib.auth.models import Group
from django.db.utils import IntegrityError

from django.utils.safestring import mark_safe

from django.template import Context, Template
from django.template.loader import get_template

from mailer import send_mail, send_html_mail
from cis.models.teacher_applicant import (
    TeacherApplication,
    TeacherApplicant,
    ApplicantSchoolCourse
)
from cis.models.customuser import CustomUser
from cis.models.note import TeacherApplicationNote

from cis.settings.incomplete_si_application import incomplete_si_application

# Nested (editable submodule) layout first, then the flat pip install.
_CANDIDATES = (
    'instructor_app.instructor_app.management.commands.notify_incomplete_si_app',
    'instructor_app.management.commands.notify_incomplete_si_app',
)


def _load_instructor_app_command():
    """Return instructor_app's Command class, or None if the app is absent.

    find_spec first so that a genuine ImportError *inside* instructor_app
    propagates instead of being swallowed as "not installed" — that would put us
    straight back to failing silently.
    """
    for path in _CANDIDATES:
        try:
            spec = importlib.util.find_spec(path)
        except (ImportError, ValueError):
            # Parent package missing, or not a package at all.
            continue
        if spec is not None:
            return import_module(path).Command
    return None


class _LegacyCommand(BaseCommand):

    help = 'Register reports in DB'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):

        from cis.settings.inst_app_language import inst_app_language
        app_settings = inst_app_language.from_db()
        accepting_applications = True if app_settings.get('is_accepting_new', 'No') == 'Yes' else False
        
        if not accepting_applications:
            return
            
        incomplete_si_application_settings = incomplete_si_application.from_db()
        if incomplete_si_application_settings.get('is_active', 'No') != 'Yes':
            return
        
        frequency = int(incomplete_si_application_settings.get('frequency', '2'))
        
        user = CustomUser.objects.get(
            username='cron'
        )

        in_progress_apps = TeacherApplication.objects.filter(
            status__iexact='in progress'
        )

        emails_sent = 0
        for app in in_progress_apps:
            misc_info = app.misc_info

            last_notified = misc_info.get(
                'last_notified_on', '10/10/2020'
            )

            if not app.needs_notification(last_notified, frequency):
                continue

            missing_items = []
            if not app.has_selected_course():
                missing_items.append('Select interested course(s)')
            else:
                if not app.has_received_recommendation():
                    item = 'Waiting for recommendation letter'
                    
                    if misc_info.get('recommender_email'):
                        rec_email = misc_info.get('recommender_email')

                        if not app.has_recommender_submitted(rec_email):
                            # Resend recommendation request
                            app.send_recommendation_request(
                                misc_info.get('recommender_name'),
                                misc_info.get('recommender_email')
                            )
                            misc_info['recommendation_requested_on'] = datetime.now().strftime('%m/%d/%Y')

                            item += f" (Reminder has been sent to {misc_info.get('recommender_name')})"
                        
                        if misc_info.get('recommender_name_2'):
                            if not app.has_recommender_submitted(
                                misc_info.get('recommender_email_2')):
                                app.send_recommendation_request(
                                    misc_info.get('recommender_name_2'),
                                    misc_info.get('recommender_email_2')
                                )
                                
                                item += f" (Reminder has been sent to {misc_info.get('recommender_name_2')})"

                    missing_items.append(item)
                if not app.has_submitted_ed_bg():
                    missing_items.append('Missing Education Background')
                if not app.has_uploaded_material():
                    missing_items.append('Upload supporting materials')

            if not missing_items:
                continue

            subject = incomplete_si_application_settings.get('email_subject')
            message = Template(incomplete_si_application_settings.get('email_message'))
            context = Context({
                'missing_items': mark_safe('<br>'.join(missing_items)),
                'teacher_first_name': app.user.first_name,
                'teacher_last_name': app.user.last_name
            })
            text_body = message.render(context)

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            if getattr(settings, 'DEBUG', True) or incomplete_si_application_settings.get('is_active', 'No') == 'Debug':
                to = ['kadaji@gmail.com']
            else:
                to = [app.user.email]

            misc_info['last_notified_on'] = datetime.now().strftime('%m/%d/%Y')
            app.misc_info = misc_info
            app.save()

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
            
            note = TeacherApplicationNote(
                teacher_application=app,
                note=text_body,
                createdby=user,
                meta={'type':'Private'}
            )
            note.save()
            emails_sent += 1
            

_delegate = _load_instructor_app_command()

# instructor_app owns this command wherever it is installed; `cis` keeps the
# name resolvable for tenants still on the legacy models.
Command = _delegate if _delegate is not None else _LegacyCommand
