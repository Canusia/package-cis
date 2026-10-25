from datetime import date
import email, json
from django.core.management.base import BaseCommand

from cis.management.campus_command import CampusCommand
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

# ClassSection.status codes for a cancelled section (CLASS_STATUS 'C').
CANCELLED_STATUSES = ('C',)


def sections_missing_syllabi(term_ids):
    """Sections in term_ids with no syllabus uploaded. Cancelled sections
    are skipped, so their instructors are not asked for a syllabus (#117)."""
    return ClassSection.objects.filter(
        term__id__in=term_ids
    ).exclude(
        id__in=ClassSectionSyllabi.objects.filter(
            class_sections__term__id__in=term_ids
        ).values_list('class_sections__id')
    ).exclude(status__in=CANCELLED_STATUSES)


def sections_needing_update(term_ids):
    """Sections in term_ids marked needs update. Cancelled sections and
    sections with no instructor are skipped (#127)."""
    return ClassSection.objects.filter(
        term__id__in=term_ids,
        syllabi_status__iexact='needs update',
        teacher__user__isnull=False,
    ).exclude(
        status__in=CANCELLED_STATUSES
    ).select_related('teacher__user', 'course', 'term').order_by(
        'course__name', 'class_number')


def _section_label(section):
    return f'{section.course.name}/{section.class_number or ""}/{section.section_number or ""}'


def needs_update_context(recipient):
    """Template context for one instructor's needs-update reminder.

    {{section_list}} has one line per section with its note. {{course}} and
    {{note}} are the section's own for a single section; for several they
    name every course and fall back to the list, so a saved template that
    predates {{section_list}} still shows every section.
    """
    from django.utils.html import format_html_join
    from django.utils.safestring import mark_safe
    sections = recipient['sections']

    def note(section):
        return (section.syllabi_status_changed_on or {}).get('note') or ''

    section_list = format_html_join(
        mark_safe('<br>'), '{}{}',
        ((_section_label(s), f' - {note(s)}' if note(s) else '') for s in sections))
    if len(sections) == 1:
        course, note_text = str(sections[0].course), note(sections[0])
    else:
        course = ', '.join(dict.fromkeys(str(s.course) for s in sections))
        note_text = section_list
    return {
        'instructor_first_name': recipient.get('first_name'),
        'instructor_last_name': recipient.get('last_name'),
        'term': str(recipient.get('term')),
        'course': course,
        'course_name': course,
        'note': note_text,
        'section_list': section_list,
    }


class Command(CampusCommand):
    help = 'Syllabus Review Emails'

    def add_arguments(self, parser):
        super().add_arguments(parser)  # --campus (MC-11)
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

        starting_date = datetime.strptime(email_settings.get('starting_date'), "%m/%d/%Y").date()
        ending_date = datetime.strptime(email_settings.get('ending_date'), "%m/%d/%Y").date()

        # compare dates so the start and end dates are both included (#117)
        today = date.today()
       
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
        classes_with_missing_syllabi = sections_missing_syllabi(
            email_settings.get('term')
        )

        # one email per instructor per term, so {{term}} matches the
        # sections listed (#117)
        email_summary = {}
        for section in classes_with_missing_syllabi:
            if section.teacher:
                key = (section.teacher.user.id, section.term_id)
                if not email_summary.get(key):
                    email_summary[key] = {
                        'first_name': section.teacher.user.first_name,
                        'last_name': section.teacher.user.last_name,
                        'secondary_email': section.teacher.user.secondary_email,
                        'email': section.teacher.user.email,
                        'term': section.term,
                        'sections': []
                    }

                email_summary[key]['sections'].append(
                    section
                )

        emails_sent = 0
        for key, recipient in email_summary.items():
        
            subject, source = syllabi_review.email_template(
                'missing_syllabus', email_settings)
            message = Template(source)

            context = Context({
                'instructor_first_name': recipient.get('first_name'),
                'instructor_last_name': recipient.get('last_name'),
                'term': str(recipient.get('term')),
                'section_list': ', '.join(
                    _section_label(sect) for sect in recipient.get('sections'))
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

        summary += f'Sent {emails_sent} missing syllabus notification(s) (one per instructor per term).\r\n'

        # Needs-update reminder: one email per instructor per term, like the
        # missing-syllabus email (#127). {{section_list}} lists each section
        # with its reviewer note.
        email_summary = {}
        for section in sections_needing_update(email_settings.get('term')):
            key = (section.teacher.user.id, section.term_id)
            if not email_summary.get(key):
                email_summary[key] = {
                    'first_name': section.teacher.user.first_name,
                    'last_name': section.teacher.user.last_name,
                    'email': section.teacher.user.email,
                    'term': section.term,
                    'secondary_email': section.teacher.user.secondary_email,
                    'sections': []
                }
            email_summary[key]['sections'].append(section)

        emails_sent = 0
        for key, recipient in email_summary.items():

            subject, source = syllabi_review.email_template(
                'needs_update', email_settings)
            message = Template(source)

            context = Context(needs_update_context(recipient))
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

        summary += f'Sent {emails_sent} needs update reminder(s) (one per instructor per term).\r\n'

        pending_review = ClassSection.objects.filter(
            term__id__in=email_settings.get('term'),
            syllabi_status__iexact='pending review'
        ).exclude(
            status__in=CANCELLED_STATUSES
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