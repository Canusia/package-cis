from datetime import date
import email, json
from django.core.management.base import BaseCommand
from django.core.validators import validate_email

from django.conf import settings
from django.db.models import Count

from django.template import Context, Template
from django.template.loader import get_template, render_to_string
from django.shortcuts import render
from django.http import HttpResponse

from mailer import send_mail, send_html_mail

from cis.signals.crontab import cron_task_done, cron_task_started
from cis.models.section import ClassSection, ClassSectionSyllabi
from cis.models.term import Term
from cis.models.course import CourseAdministrator

class Command(BaseCommand):
    help = 'Syllabus Review Emails'

    def add_arguments(self, parser):
        parser.add_argument('-t', '--time', type=str, help='Time of run')

    def handle(self, *args, **kwargs):
        from datetime import datetime, timedelta
        from cis.settings.syllabi_review import syllabi_review

        from cis.utils import (
            getDomain, upload_to_s3
        )
        
        if kwargs.get('time'):
            time = kwargs['time']

            cron_task_started.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time
            )

        summary = ''
        detailed_log = {
            'missing_syllabus': [],
            'needs_update_reminder': [],
            'faculty_pending_review': [],
        }

        from cis.models.student import Student
        from cis.models.note import StudentNote
        
        email_settings = syllabi_review.from_db()

        starting_date = datetime.strptime(email_settings.get('starting_date'), "%m/%d/%Y")
        ending_date = datetime.strptime(email_settings.get('ending_date'), "%m/%d/%Y")

        today = datetime.now()
       
        test_mode = True if email_settings.get('mode').lower() == 'test' else False
        testers = email_settings.get('testers', 'kadaji@gmail.com').split(',')

        if (today < starting_date) or (today > ending_date):
            summary = "Skipping emails"
            if kwargs.get('time'):
                cron_task_done.send(
                    sender=self.__class__,
                    task=self.__class__,
                    scheduled_time=time,
                    summary=summary,
                    detailed_log=json.dumps(detailed_log)
                )
            return

        # get all teachers who have not uploaded syllabus
        classes_with_missing_syllabi = ClassSection.objects.filter(
            term__id__in=email_settings.get('term')
        ).exclude(
            id__in=ClassSectionSyllabi.objects.filter(
                class_sections__term__id__in=email_settings.get('term')
            ).values_list('class_sections__id')
        )

        email_summary = {}
        for section in classes_with_missing_syllabi:
            if section.teacher:
                if not email_summary.get(section.teacher.user.id):
                    email_summary[section.teacher.user.id] = {
                        'first_name': section.teacher.user.first_name,
                        'last_name': section.teacher.user.last_name,
                        'secondary_email': section.teacher.user.secondary_email,
                        'email': section.teacher.user.email,
                        'term': section.term,
                        'sections': []
                    }

                email_summary[section.teacher.user.id]['sections'].append(
                    section
                )

        emails_sent = 0
        for user_id, recipient in email_summary.items():
        
            subject = email_settings.get('missing_syllabus_email_subject', 'change me')
            message = Template(email_settings.get('missing_syllabus_email_message', 'change'))

            context = Context({
                'instructor_first_name': recipient.get('first_name'),
                'instructor_last_name': recipient.get('last_name'),
                'term': str(recipient.get('term')),
                'section_list': ', '.join(
                    [ 
                        sect.course.name + '/' + str(sect.class_number) + '/' + sect.section_number for sect in recipient.get('sections') 
                    ]
                )
            })
            text_body = message.render(context)

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            to = []

            try:
                validate_email(recipient.get('email'))
                to.append(recipient.get('email'))
            except:
                ...

            try:
                validate_email(recipient.get('secondary_email'))
                to.append(recipient.get('secondary_email'))
            except:
                ...

            if not to or test_mode:
                to = testers


            detailed_log['missing_syllabus'].append(to)
            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
            emails_sent += 1

        summary += f'Sent missing syllabus notification to {emails_sent} instructors.\r\n'

        # notify teachers will no syllabus marked as needs update
        classes_with_syl_needs_update = ClassSection.objects.filter(
            term__id__in=email_settings.get('term'),
            syllabi_status__iexact='needs update'
        )

        email_summary = {}
        for section in classes_with_syl_needs_update:
            if not email_summary.get(section.id):
                email_summary[section.id] = {
                    'first_name': section.teacher.user.first_name,
                    'last_name': section.teacher.user.last_name,
                    'email': section.teacher.user.email,
                    'term': section.term,
                    'secondary_email': section.teacher.user.secondary_email,
                    'sections': []
                }
            email_summary[section.id]['sections'].append(
                section
            )

        print(email_summary)
        emails_sent = 0
        for user_id, recipient in email_summary.items():
        
            subject = email_settings.get('needs_update_email_subject', 'change me')
            
            message = Template(email_settings.get('needs_update_email_message', 'change'))

            context = Context({
                'instructor_first_name': recipient.get('first_name'),
                'instructor_last_name': recipient.get('last_name'),
                'term': str(recipient.get('last_name')),
                'course': str(recipient['sections'][0].course),
                'note': 'Note added by faculty - change me'
            })
            text_body = message.render(context)

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            to = []

            try:
                validate_email(recipient.get('email'))
                to.append(recipient.get('email'))
            except:
                ...

            try:
                validate_email(recipient.get('secondary_email'))
                to.append(recipient.get('secondary_email'))
            except:
                ...

            if not to or test_mode:
                to = testers

            detailed_log['needs_update_reminder'].append(to)
            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
            emails_sent += 1

        summary += f'Sent needs update reminders to {emails_sent} class sections.\r\n'

        pending_review = ClassSection.objects.filter(
            term__id__in=email_settings.get('term'),
            syllabi_status__iexact='pending review'
        ).exclude(
            status='cancelled'
        ).values(
            'course__name', 'teacher__user__first_name', 'teacher__user__last_name'
        ).annotate(
            total=Count('course__name')
        )

        notif_list = {}

        for pending_course in pending_review:
            if pending_course['total'] > 0:
                # get course admin
                course_admins = CourseAdministrator.objects.filter(
                    course__name=pending_course['course__name'],
                    status='Active',
                    role__in=['Faculty', 'Visitor']
                ).distinct('user')

                for course_admin in course_admins:
                    notif_list[
                        course_admin.user.email
                    ] = {
                        'first_name': course_admin.user.first_name,
                        'last_name': course_admin.user.last_name,
                    }

                    if not notif_list[course_admin.user.email].get('teachers'):
                        notif_list[course_admin.user.email]['teachers'] = []                    
                    
                    notif_list[course_admin.user.email].get('teachers').append(pending_course['teacher__user__first_name'] + ' ' + pending_course['teacher__user__last_name'] + ' - ' + pending_course['course__name'])

        # for email, user_info in notif_list.items():

        #     subject = email_settings.get('faculty_pending_review_email_subject', 'change me')
        #     if subject == 'change me':
        #         continue

        #     message = Template(email_settings.get('faculty_pending_review_email_message', 'change'))

        #     context = Context({
        #         'faculty_first_name': user_info.get('first_name'),
        #         'faculty_last_name': user_info.get('last_name'),
        #         'teachers': '<br>'.join(user_info.get('teachers'))
        #         # 'term': str(term),
        #     })
        #     text_body = message.render(context)

        #     template = get_template('cis/email.html')
        #     html_body = template.render({
        #         'message': text_body
        #     })

        #     to = []

        #     try:
        #         validate_email(email)
        #         to.append(recipient.get('email'))
        #     except:
        #         ...

        #     try:
        #         validate_email(recipient.get('secondary_email'))
        #         to.append(recipient.get('secondary_email'))
        #     except:
        #         ...

        #     if not to or test_mode:
        #         to = testers
                
        #     send_html_mail(
        #         subject,
        #         text_body,
        #         html_body,
        #         settings.DEFAULT_FROM_EMAIL,
        #         to
        #     )
        #     detailed_log['faculty_pending_review'].append(to)
        #     emails_sent += 1

        # summary += f'Sent pending review notification to {emails_sent} faculty.\r\n'
        
        if kwargs.get('time'):
            cron_task_done.send(
                sender=self.__class__,
                task=self.__class__,
                scheduled_time=time,
                summary=summary,
                detailed_log=json.dumps(detailed_log)
            )