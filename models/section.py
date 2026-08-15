# users/models.py
import os, uuid, datetime, json, logging

from django.conf import settings
from django.db import models, IntegrityError
from django.dispatch import receiver
from django.urls import reverse_lazy

from django.core.mail import EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import get_template
from django.http import JsonResponse, HttpResponse

from simple_history.models import HistoricalRecords

from django.utils.safestring import mark_safe
from django.db.models import JSONField
from django.core.validators import validate_email

from mailer import send_mail, send_html_mail

from model_utils import FieldTracker

from cis.utils import (
    export_to_excel, syllabus_upload_path, format_emplid,
    extract_class_times, model_as_HTML,
    REGISTRATION_TYPES,
    registration_terms as get_registration_terms,
    upload_to_s3
)

from cis.storage_backend import PrivateMediaStorage

from cis.models.note import ClassSectionNote
from cis.models.term import Term, AcademicYear
from cis.models.course import Course, Campus, Location, Cohort
from cis.models.settings import Setting

logger = logging.getLogger(__name__)


def _get_visit_schedule_model():
    """Lazy import to avoid circular dependency with class_visit."""
    from class_visit.models import VisitSchedule  # noqa: PLC0415
    return VisitSchedule


class SectionNumber(models.Model):
    """
    Section Number model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=100, blank=True)
    number = models.CharField(max_length=5)

    CE_ACADEMIC = 'Concurrent Enrollment (Academic)'
    CE_VOCATIONAL = 'Concurrent Enrollment (Vocational)'
    IVC = 'Interactive Video Conference (IVC)'
    HYBRID = 'Hybrid'
    F2F = 'Face-to-Face (F2F)'
    ONLINE = 'Online'
    CTE = 'Career and Technical Education (CTE)'
    CTE_RICHFIELD = 'CTE Richfield Campus'
    CTE_ONLINE_RICHFIELD = 'Online CTE Richfield Campus'
    CTE_EPHRAIM = 'CTE Ephraim Campus'

    TYPE_OPTIONS = [
        ('', '---'),
        (CE_ACADEMIC, 'Concurrent Enrollment (Academic)'),
        (CE_VOCATIONAL, 'Concurrent Enrollment (Vocational)'),
        (IVC, IVC),
        (HYBRID, HYBRID),
        (F2F, F2F),
        (ONLINE, ONLINE),
        (CTE, CTE),
        (CTE_RICHFIELD, CTE_RICHFIELD),
        (CTE_ONLINE_RICHFIELD, CTE_ONLINE_RICHFIELD),
        (CTE_EPHRAIM, CTE_EPHRAIM)
    ]
    
    section_type = models.CharField(max_length=50, choices=TYPE_OPTIONS)
    highschool = models.ForeignKey(
        'cis.HighSchool',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    class Meta:
        unique_together = ['number']

    def __str__(self):
        return self.number

from myce.models import MyCEBaseModel
class ClassSection(MyCEBaseModel):
    """
    Class Section model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class_number = models.CharField(max_length=50)
    section_number = models.CharField(max_length=10)

    # this is not used
    highschool_course_title = models.CharField(max_length=500, blank=True, null=True)
    # section_number = models.ForeignKey('cis.SectionNumber', on_delete=models.PROTECT)

    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    term = models.ForeignKey('cis.Term', on_delete=models.PROTECT)
    registration_term = models.ForeignKey(
        'cis.Term',
        on_delete=models.PROTECT,
        related_name='registration_term',
        blank=True,
        null=True,
        verbose_name='Registration Term'
    )

    highschool = models.ForeignKey(
        'cis.HighSchool',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    highschool_course_name = models.CharField(max_length=500, blank=True)

    teacher = models.ForeignKey(
        'cis.Teacher',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    course = models.ForeignKey('cis.Course', on_delete=models.PROTECT)
    campus = models.ForeignKey('cis.Campus', blank=True, on_delete=models.PROTECT, null=True)
    location = models.ForeignKey(
        'cis.Location',
        on_delete=models.PROTECT,
        blank=True,
        null=True
    )

    co_reqs = models.ManyToManyField('cis.ClassSection', blank=True)
    credit_hours = models.FloatField(default=1)

    days = models.CharField(max_length=50, blank=True)
    start_time = models.IntegerField(default=0)
    end_time = models.IntegerField(default=0)

    room = models.CharField(max_length=50, blank=True)

    instruction_mode = models.CharField(max_length=50, blank=True, null=True)
    prereq = models.TextField(blank=True)

    max_enrollment = models.IntegerField(default=0)
    min_enrollment = models.IntegerField(default=0)

    lab_fees = models.FloatField(default=0)
    tuition = models.FloatField(default=0)

    enrollment = models.IntegerField(default=0)
    available_seats = models.IntegerField(default=0)

    last_imported_on = models.DateField(auto_now=True)

    syllabi = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=syllabus_upload_path,
        blank=True)

    room_alias = models.CharField(max_length=10, blank=True, null=True)

    meta = JSONField(default=dict)
    
    # Fields that can be updated during import or update operations
    UPDATABLE_FIELDS = [
        'section_number',
        'course',
        'credit_hours',
        'start_time',
        'end_time',
        'start_date',
        'end_date',
        'prereq',
        'highschool_course_name',
        'location',
        'instruction_mode',
        'highschool',
        'teacher',
        'part_of_term',
        'tuition',
        'status',
        'registration_term',
        'free_period',
        'period_time',
    ]

    notifications = JSONField(blank=True, null=True)
    
    tracker = FieldTracker(fields=['roster_status', 'grade_status', 'syllabi_status'])

    period_time = models.CharField(max_length=500, blank=True, null=True)
    free_period = models.CharField(max_length=500, blank=True, null=True)

    ROSTER_STATUS = (
        ('', ''),
        ('pending verification', 'Pending Verification'),
        ('accurate', 'Accurate'),
        ('inaccurate', 'Inaccurate'),
    )
    roster_status = models.CharField(
        max_length=30,
        choices=ROSTER_STATUS,
        default='',
        blank=True,
        null=True
    )

    CLASS_STATUS = (
        ('A', 'Active'),
        ('C', 'Cancelled'),
    )
    status = models.CharField(
        max_length=30,
        choices=CLASS_STATUS,
        default='A',
        blank=True,
        null=True
    )

    roster_status_changed_on = JSONField(blank=True, null=True)

    SYLLABI_STATUS = (
        ('', ''),
        ('pending review', 'Pending Review'),
        ('reviewed', 'Reviewed'),
        ('needs update', 'Needs Update'),
    )
    syllabi_status = models.CharField(
        max_length=30,
        choices=SYLLABI_STATUS,
        default='',
        blank=True,
        null=True
    )
    syllabi_status_changed_on = JSONField(default=dict)

    # Start Grades Module
    GRADE_STATUS = (
        ('', 'N/A'),
        ('saved', 'Grades Saved Only'),
        ('submitted', 'Grades Successfully Submitted')
    )
    grade_status = models.CharField(
        max_length=30,
        choices=GRADE_STATUS,
        default='',
        blank=True,
        null=True
    )
    grade_status_changed_on = JSONField(
        blank=True,
        null=True
    )

    @property
    def grade_submitted(self):
        return self.grade_status == 'submitted'
    
    part_of_term = models.CharField(max_length=50, blank=True)
    
    class Meta:
        unique_together = (("class_number", "term", 'campus'))

    # @property
    # def registration_term(self):
    #     return self.term
    
    @property
    def invoice_description(self):
        return f"{self.term} / {self.course.name} - {self.highschool_course_name} ({self.course.credit_hours} cr.)"
    
    @property
    def school_cost(self):
        return 0
    
    @property
    def student_cost(self):
        return self.tuition + self.lab_fees

    @property
    def sis_id(self):
        # external_sis_id is the canonical field populated by the Ethos
        # section importer. meta['section_id'] is legacy (set by
        # import_class_guids management command and the section form).
        return self.external_sis_id or self.meta.get('section_id')
    
    @property
    def is_a_co_req(self):
        return ClassSection.objects.filter(co_reqs__id=self.id).exists()
    
    def add_note(self, createdby=None, note='', meta=None):

        from cis.models.note import ClassSectionNote
        from cis.models.customuser import CustomUser
        
        if not createdby:
            createdby = CustomUser.objects.get(
                username='cron'
            )

        note = ClassSectionNote(
            createdby=createdby,
            note=note,
            class_section=self
        )

        if not meta:
            meta = {'type': 'Private'}

        note.meta = meta
        note.save()

        return note
    
    def download_roster_pdf(self):
        import pdfkit, datetime
    
        base_template = 'cis/sections/class_roster.html'
        template = get_template(base_template)

        students = StudentRegistration.objects.filter(
            class_section=self,
            status='registered'
        ).order_by('student__user__last_name')

        html = template.render({
            'students': students,
            'generated_on': datetime.datetime.now(),
            'class_section': self,
        })
        
        options = {
            'page-size': 'Letter'
        }
        pdf = pdfkit.from_string(html, False, options)

        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename=' + "class_roster_" + str(self.class_number) + "_" + self.term.code + ".pdf"
        
        return response

    @property
    def syllabi_note(self):
        from cis.settings.syllabi_review import syllabi_review as syl_review

        template = Template(syl_review.from_db().get('instructor_message', ''))
        context = Context({
            'note': self.syllabi_status_changed_on.get('note', '')
        })

        return template.render(context)
    
    def mark_syllabi_as_reviewed(self, note='', updated_by=None):
        self.syllabi_status = 'reviewed'
        
        class_note = ClassSectionNote(
            class_section=self,
            note='Marked syllabi as reviewed.',
            createdby=updated_by,
            meta={
                'type': 'public'
            }
        )

        class_note.save()
        self.save()

        from cis.settings.syllabi_review import syllabi_review as syl_settings
        notif_settings = syl_settings.from_db()

        email_subject = notif_settings.get('email_subject')
        email_text = notif_settings.get('email_message_reviewed')

        message = Template(email_text)
        context = Context({
            'instructor_first_name': self.teacher.user.first_name,
            'instructor_last_name': self.teacher.user.last_name,
            'course_name': self.course,
            'term': self.term
        })

        send_to = [self.teacher.user.secondary_email, self.teacher.user.email]
        if notif_settings.get('mode') == 'test':
            send_to = notif_settings.get('testers').split(',')

        text_body = message.render(context)

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            email_subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            send_to
        )


    # def mark_syllabi_as_needs_update(self, note='', updated_by=None):
    #     self.syllabi_status = 'needs update'
    #     self.syllabi_status_changed_on['note'] = note

    #     class_note = ClassSectionNote(
    #         class_section=self,
    #         note='Marked syllabi as needs update.<br><br>' + note,
    #         createdby=updated_by,
    #         meta={
    #             'type': 'public'
    #         }
    #     )

    #     class_note.save()
    #     self.save()

    #     from cis.settings.syllabi_review import syllabi_review as syl_settings
    #     notif_settings = syl_settings.from_db()

    #     email_subject = notif_settings.get('email_subject')
    #     email_text = notif_settings.get('email_message')

    #     message = Template(email_text)
    #     context = Context({
    #         'instructor_first_name': self.teacher.user.first_name,
    #         'instructor_last_name': self.teacher.user.last_name,
    #         'course_name': self.course,
    #         'term': self.term,
    #         'note': note
    #     })

    #     send_to = [self.teacher.user.secondary_email]
    #     if notif_settings.get('mode') == 'test':
    #         send_to = notif_settings.get('testers').split(',')

    #     text_body = message.render(context)

    #     template = get_template('cis/email.html')
    #     html_body = template.render({
    #         'message': text_body
    #     })

    #     send_html_mail(
    #         email_subject,
    #         text_body,
    #         html_body,
    #         settings.DEFAULT_FROM_EMAIL,
    #         send_to
    #     )

    def mark_syllabi_as_needs_update(self, note='', updated_by=None):
        self.syllabi_status = 'needs update'
        self.syllabi_status_changed_on['note'] = note
        self.syllabi_status_changed_on['reviewed_on'] = datetime.datetime.now().strftime('%m/%d/%Y')

        try:
            # update all sections for which syllabi is associated with
            class_section_syllabi = ClassSectionSyllabi.objects.filter(
                class_sections=self
            )

            class_section_syllabi[0].class_sections.all().update(
                syllabi_status='needs update'
            )
        except:
            ...

        class_note = ClassSectionNote(
            class_section=self,
            note='Marked syllabi as needs update.<br><br>' + note,
            createdby=updated_by,
            meta={
                'type': 'public'
            }
        )

        class_note.save()
        self.save()

        from cis.settings.syllabi_review import syllabi_review as syl_settings
        notif_settings = syl_settings.from_db()

        email_subject = notif_settings.get('email_subject')
        email_text = notif_settings.get('email_message')

        message = Template(email_text)
        context = Context({
            'instructor_first_name': self.teacher.user.first_name,
            'instructor_last_name': self.teacher.user.last_name,
            'course_name': self.course,
            'term': self.term,
            'note': note
        })

        send_to = [self.teacher.user.secondary_email, self.teacher.user.email]
        if notif_settings.get('mode') == 'test':
            send_to = notif_settings.get('testers').split(',')

        text_body = message.render(context)

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            email_subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            send_to
        )

    @property
    def syllabi(self):
        return ClassSectionSyllabi.objects.filter(
            class_sections__in=[self]
        )

    @property
    def syllabi_links(self):
        links = []
        for syl in self.syllabi:
            links.append(
                f"<a href='{syl.media.name}'>{syl.filename}</a>"
            )
        return links
        
    @property
    def visit_schedule(self):
        VisitSchedule = _get_visit_schedule_model()
        return VisitSchedule.objects.filter(
            class_sections=self
        )

    @property
    def has_visit_to_other_section(self):
        VisitSchedule = _get_visit_schedule_model()
        return VisitSchedule.objects.filter(
            class_sections__term=self.term,
            class_sections__teacher=self.teacher,
            class_sections__course=self.course
        ).exclude(
            class_sections__id=self.id
        ).exists()

    # @property
    # def tuition(self):
    #     costs = []

    #     if self.lab_fees:
    #         costs.append(
    #             ('Lab Fees', self.lab_fees)
    #         )

    #     if self.term.academic_year.cost_per_credit:
    #         costs.append(
    #             (
    #                 f'Tuition for {self}', self.term.academic_year.cost_per_credit * self.course.credit_hours
    #             )
    #         )
        
    #     return costs

    @property
    def last_notified_roster_request(self):
        return self.last_notified()

    def update_last_notified(self, notif_type='roster_verification'):
        notifications = self.notifications
        
        if not notifications:
            notifications = {}
        notifications[notif_type] = datetime.datetime.now().strftime("%m/%d/%Y")

        ClassSection.objects.filter(
            pk=self.id
        ).update(
            notifications=notifications
        )

    def last_notified(self, notif_type='roster_verification'):
        notifications = self.notifications
        
        if not notifications:
            return '11/18/2018'

        return notifications.get(notif_type) if notifications.get(notif_type) else '11/18/2018'

    def needs_roster_verification_reminder(self):
        if self.roster_status != 'pending verification':
            return False

        from cis.settings.roster_verification import (
            roster_verification as roster_verification_settings
        )
        notif_settings = roster_verification_settings.from_db()

        last_notified = self.last_notified('roster_verification')
        current_date = datetime.datetime.now()

        num_days = int(notif_settings.get('frequency', 3))
        last_notified = datetime.datetime.strptime(last_notified, "%m/%d/%Y")

        return True if abs((current_date - last_notified).days) >= num_days else False

    def needs_ce_notificaton_on_roster_change(self):
        from cis.settings.roster_verification import (
            roster_verification as roster_verification_settings
        )
        notif_settings = roster_verification_settings.from_db()

        return True if self.roster_status in notif_settings.get('notify_status', []) else False

    def notify_ce_staff_on_roster_change(self):
        from cis.settings.roster_verification import (
            roster_verification as roster_verification_settings
        )
        notif_settings = roster_verification_settings.from_db()

        email_subject = notif_settings.get('notify_verify_confirmation_subject')
        if not email_subject:
            return None

        email_text = notif_settings.get('notify_verify_email')

        send_to = notif_settings.get('notify_address').split(',')

        if getattr(settings, 'DEBUG', True):
            send_to = ['kadaji@gmail.com']
        
        message = Template(email_text)
        context = Context({
            'teacher_first_name': self.teacher.user.first_name,
            'teacher_last_name': self.teacher.user.last_name,
            'crn': self.class_number,
            'highschool': self.highschool.name if self.highschool else '',
            'course_name': self.course,
            'section_number': self.section_number,
            'term': self.term,
            'roster_status': self.roster_status,
            'note': self.notifications.get('roster_verification_note', '') if self.notifications else ''
        })

        text_body = message.render(context)

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            email_subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            send_to
        )
        return True

    def notify_teacher_on_roster_verification(
        self,
        email_subject=None,
        email_message=None,
        send_mode='active',
        debug_list=None
    ):
        from cis.utils import is_valid_email
        """
        Send roster verification request
        """
        if not self.teacher:
            return
        
        if not email_subject:
            from cis.settings.roster_verification import (
                roster_verification as roster_verification_settings
            )
            notif_settings = roster_verification_settings.from_db()

            email_subject = notif_settings.get('request_verify_subject')
            email_message = notif_settings.get('request_verify_email')
            send_mode = notif_settings.get('mode', 'debug')
            debug_list = notif_settings.get('notify_address', 'kadaji@gmail.come').split(',')

        email_subject = email_subject

        email_subject = Template(email_subject)
        context = Context({
            'class_number': self.class_number,
            'highschool': self.highschool.name if self.highschool else '',
            'course_name': self.course,
            'section_number': self.section_number,
            'term': self.term
        })
        email_subject = email_subject.render(context)

        email_text = email_message

        send_to = []
        if is_valid_email(self.teacher.user.email):
            send_to.append(self.teacher.user.email)
            
        if self.teacher.user.secondary_email and is_valid_email(self.teacher.user.secondary_email):
            send_to.append(self.teacher.user.secondary_email)

        if send_mode == 'debug':
            if not debug_list:
                debug_list = ['kadaji@gmail.com']

            send_to = debug_list
        
        message = Template(email_text)
        context = Context({
            'teacher_first_name': self.teacher.user.first_name,
            'teacher_last_name': self.teacher.user.last_name,
            'class_number': self.class_number,
            'highschool': self.highschool.name if self.highschool else '',
            'course_name': self.course,
            'section_number': self.section_number,
            'term': self.term,
            'note': self.notifications.get('roster_verification_note', '') if self.notifications else ''
        })

        text_body = message.render(context)

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            email_subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            send_to
        )

        self.update_last_notified()
        return True
    @classmethod
    def notify_sections_pending_roster_verification(cls, *args, **kwargs):
        summary = ''
        detailed_log = {
            'notified_crn': [],
            'pending_crn': [],
            'notified_teacher': [],
            'failed_crn': [],
        }

        from cis.settings.roster_verification import (
            roster_verification as roster_verification_settings
        )
        notif_settings = roster_verification_settings.from_db()

        pending_verification = ClassSection.objects.filter(
            roster_status__iexact='pending verification'
        )

        summary += 'Found ' + str(pending_verification.count()) + ' sections marked as pending verification'

        success, failed = 0, 0
        for pending in pending_verification:
            if not pending.teacher:
                continue
            
            detailed_log['pending_crn'].append(
                str(pending.class_number) + ' - ' + str(pending.last_notified())
            )

            if pending.needs_roster_verification_reminder():
                
                sent = pending.notify_teacher_on_roster_verification(
                    notif_settings.get('request_verify_subject'),
                    notif_settings.get('request_verify_email'),
                    notif_settings.get('mode', 'debug'),
                    notif_settings.get('notify_address', 'kadaji@gmail.come').split(',')
                )

                if sent:
                    success += 1
                    detailed_log['notified_crn'].append(
                        pending.class_number
                    )
                    detailed_log['notified_teacher'].append(
                        str(pending.teacher)
                    )

                    pending.add_note(None, 'Sent pending roster verification email')
                else:
                    failed += 1
                    detailed_log['failed_crn'].append(
                        pending.class_number
                    )

                    pending.add_note(None, 'Failed to Send pending roster verification email')

        summary += f"\r\nSuccessfully sent {success}. Failed to send {{failed}}"
        return (summary, detailed_log)

    def notify_teacher_on_roster_confirmed(self):
        from cis.settings.roster_verification import (
            roster_verification as roster_verification_settings
        )
        notif_settings = roster_verification_settings.from_db()

        email_subject = notif_settings.get('verify_confirmation_subject')
        if not email_subject:
            return None

        email_text = notif_settings.get('verify_confirmation_email')

        send_to = [self.teacher.user.email]

        if getattr(settings, 'DEBUG', True):
            send_to = ['kadaji@gmail.com']
        
        message = Template(email_text)
        context = Context({
            'teacher_first_name': self.teacher.user.first_name,
            'teacher_last_name': self.teacher.user.last_name,
            'crn': self.class_number,
            'highschool': self.highschool.name if self.highschool else '',
            'course_name': self.course,
            'section_number': self.section_number,
            'term': self.term,
            'roster_status': self.roster_status_pretty
        })

        text_body = message.render(context)

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            email_subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            send_to
        )
        return True

    @property
    def roster_needs_verification(self):
        if self.roster_status == 'pending verification':
            return True
        return False

    @property
    def roster_status_pretty(self):
        if self.roster_status:
            return self.roster_status.capitalize()

    def get_notes(self, type=['public', 'to_instructor']):
        from cis.models.note import ClassSectionNote
        notes = ClassSectionNote.objects.filter(
            class_section=self,
            meta__type__in=type
        ).order_by('-createdon')

        return notes

    @staticmethod
    def delete_record(record):
        StudentRegistration.objects.filter(
            class_section=record
        ).delete()

        ClassSectionSyllabi.objects.filter(
            class_sections__pk=record.id
        ).delete()

        ClassSectionNote.objects.filter(
            class_section=record
        ).delete()

        record.delete()
    
    @property
    def _start_time(self):
        if self.start_time == 0:
            return '12:00AM'

        import time
        return time.strftime('%I:%M%p', time.strptime(str(self.start_time), '%H%M'))

    @property
    def _end_time(self):
        if self.end_time == 0:
            return '12:00AM'

        import time
        return time.strftime('%I:%M%p', time.strptime(str(self.end_time), '%H%M'))

    @property
    def sexy_info(self):
        result = ''

    @property
    def schedule(self):
        result = ''

        # if self.instruction_mode:
        #     result = self.instruction_mode + '<br>'

        try:
            result += self.start_date.strftime('%m/%d/%Y') + ' - ' + self.end_date.strftime('%m/%d/%Y') + '<br>'
        except:
            pass

        if self.days:
            result += self.days + "<br>"

        try:
            result += self._start_time + ' - ' + self._end_time
        except:
            pass

        return result

    def asHTML(self):
        from cis.settings.class_section_profile import (
            class_section_profile, CLASS_SECTION_DEFAULT_DISPLAY,
        )
        from cis.utils import resolve_display_layout

        raw = class_section_profile.from_db().get('profile_display')
        layout = resolve_display_layout(raw, CLASS_SECTION_DEFAULT_DISPLAY)
        return model_as_HTML(self, layout)

    @property
    def pretty_meta(self):
        return mark_safe('<pre style="">' + json.dumps(self.meta, indent=2) + '</pre>')

    @classmethod
    def format_class_section_data(cls, row, **kwargs):
        from datetime import datetime
        import time

        result = {}

        if row.get('START_DATE', None):
            try:
                result['start_date'] = datetime.strptime(row['START_DATE'], '%m/%d/%y').date()
            except:
                pass

        if row.get('END_DATE', None):
            try:
                result['end_date'] = datetime.strptime(row['END_DATE'], '%m/%d/%y').date()
            except:
                pass

        result['part_of_term'] = row.get('PART_OF_TERM', '')
        result['start_time'] = '0'
        result['start_time'] = '2359'
        if row.get('TIMES', None):
            try:
                result['start_time'], result['end_time'] = extract_class_times(row['TIMES'])
            except ValueError:
                ...

        # start_time = row.get('START_TIME', None)
        # end_time = row.get('END_TIME', None)
        # if start_time and end_time:
        #     start_time = int(time.strftime('%H%M', time.strptime(start_time, '%I:%M%p')))
        #     end_time = int(time.strftime('%H%M', time.strptime(end_time, '%I:%M%p')))

        # result['start_time'] = start_time
        # result['end_time'] = end_time

        result['days'] = row.get('DAYS', '')
        if row.get('MIN_ENRL', None):
            result['min_enrollment'] = row['MIN_ENRL']
        
        if row.get('MAX_ENRL', None):
            result['max_enrollment'] = row['MAX_ENRL']

        if row.get('TOT_ENRL', None):
            result['enrollment'] = row['TOT_ENRL']

        if row.get('CREDITS', None):
            result['credits'] = row['CREDITS']
        
        result['prereq'] = row.get('OFFERDESCR', '')
        # result['section_number'] = row.get('Section #', '')
        result['instruction_mode'] = row.get('INSTRUCTION_MODE')
        result['highschool_course_name'] = row.get('High School Course Title', '-')
        
        for key, value in kwargs.items():
            result[key] = value

        return result
        
    @classmethod
    def update_or_add(cls, term, class_number, **kwargs):
        """
        Docstring for update_or_add
        
        :param cls: Description
        :param term: Description
        :param class_number: Description
        :param kwargs: Description
        :return: Description
        :rtype: Callable[[Iterable[object]], bool]

        This is slated to be removed in future versions
        """
        try:
            record = ClassSection.objects.get(
                term=term,
                class_number=class_number
            )

            #update fields
            updatable_fields = [
                'section_number',
                'credit_hours',
                'start_time',
                'end_time',
                'start_date',
                'end_date',
                'meeting_days',
                'current_enrollment',
                'prereq',
                'highschool_course_name',
                'location',
                'instruction_mode',
                'highschool',
                'teacher',
                'part_of_term',
                'tuition',
                'highschool_course_name',
                'status',
                'registration_term'
            ]

            for key, value in kwargs.items():
                if key in updatable_fields:
                    setattr(record, key, value)
            record.save()

            return record
        except ClassSection.DoesNotExist:
            record = ClassSection()
            record.term = term
            record.class_number = class_number
            # record.section_number = section_number

            for key, value in kwargs.items():
                setattr(record, key, value)
            
            record.save()
            return record

    def __str__(self):
        return f"{self.course} / {self.class_number} ({self.section_number})"

    @property
    def cost(self):
        return self.tuition + self.lab_fees
    
    @property
    def ce_url(self):
        return reverse_lazy('cis:section', kwargs={
            'record_id': self.id})

    def add_offerings(self, highschools=[]):
        from cis.models.highschool import HighSchoolClassOffering

        for highschool in highschools:
            try:
                offering = HighSchoolClassOffering()
                offering.highschool = highschool
                offering.class_section = self

                offering.save()
            except:
                pass
        
    def get_syllabi(self):
        """
        Return a queryset of ClassSectionSyllabi objects
        """
        syllabi = ClassSectionSyllabi.objects.filter(
            class_sections__pk=self.id
        )
        return syllabi

    def get_students(self, status=[], highschool_ids=None):
        """
        Return a queryset of 'StudentRegistration' objects in class section who are
        in 'status'. If 'status' is empty return all 'StudentRegistration's
        """
        all_registrations = StudentRegistration.objects.filter(
            class_section=self
        ).order_by(
            'student__user__last_name'
        )

        if highschool_ids:
            all_registrations = all_registrations.filter(
                student__highschool__id__in=highschool_ids).order_by(
                'student__user__last_name'
            )

        if status and status != []:
            all_registrations = all_registrations.filter(
                status__in=status
            )

        return all_registrations

    @classmethod
    def get_ivc_sections_offered(cls, terms):
        """
        Returns a queryset of 'ClassSection' objects for the terms where
        section numbers are between 400 - 409

        terms => Queryset of type Term
        """
        classes_for_term = ClassSection.objects.filter(
            term__in=terms,
            section_number__number__gte=400,
            section_number__number__lte=409
        )
        return classes_for_term

    @classmethod
    def sections_available(highschool, terms=[]):
        """
        Return a queryset of 'ClassSection' objects for the terms.
        If terms is empty return all available sections
        """
        return ClassSection.objects.filter(
            highschool=highschool
        )


    @staticmethod
    def import_from_csv_deprecated(dictReader):
        '''
        Returns a list of OrderedDict with results after importing sections from 
        csv.DictReader object
        '''
        from cis.models.teacher import (
            Teacher, TeacherCourseCertificate,
            TeacherHighSchool
        )
        from cis.models.term import Term
        from cis.models.highschool import HighSchool

        from cis.services.importers.class_section_schema import ClassSectionRow
        required_headers = ClassSectionRow.csv_headers()
        has_headers = False
        result = []
        index = 0
        for row in dictReader:
                # print(row)
                # continue
                
                # if row['Highschool_ceeb'] != '392708':
                #    continue
                
                row['term_name'] = row['name']
                # print(f"Importing row # {row_num}")

                row['course_name'] = row['course_name'].strip().replace('  ', ' ')
                try:
                    try:
                        course = Course.objects.get(name=row['course_name'])
                    except:
                        cohort, catalog = row['course_name'].split(' ')
                        cohort, created = Cohort.objects.get_or_create(name=cohort, designator=cohort)

                        course, created = Course.objects.get_or_create(cohort=cohort, name=row['course_name'], title=row['course_title'], credit_hours=row.get('credits', 0))
                    try:
                        teacher = Teacher.objects.get(user__secondary_email=row['teacher_hs_email'])
                    except:
                        teacher = None

                    try:
                        highschool = HighSchool.objects.get(code=row['highschool_ceeb'])
                    except:
                        print(row['highschool_ceeb'])
                        # return
                        highschool = None
                        
                    # get or create term
                    try:
                        term = Term.objects.filter(
                            code=row['term_code']
                        ).first()
                    except Term.DoesNotExist:
                        row['RESULT'] = 'Term does not exist'
                        result.append(row)
                        continue
                    
                    if not Term.objects.filter(code=row['registration_term_code']).exists():
                        registration_term, created = Term.objects.get_or_create(
                            code=row['registration_term_code'],
                            label=f"{row['registration_term_code']}",
                            academic_year=AcademicYear.objects.first()
                        )
                    else:
                        registration_term = Term.objects.filter(code=row['registration_term_code']).first()

                except Exception as e:
                    print('failed')
                    print(e)
                    # row_num += 1
                    print(row)
                    # return

                    row['RESULT'] = str(e)
                    result.append(row)
                    continue

                try:
                    if row.get('YearLong', '') == '':
                        row['YearLong'] = False
                            
                    # parse date from start_date
                    try:
                        start_date = datetime.datetime.strptime(row['start_date'], '%Y-%m-%d')
                        end_date = datetime.datetime.strptime(row['end_date'], '%Y-%m-%d')
                    except:
                        start_date = None
                        end_date = None

                    class_section = ClassSection.update_or_add(
                        term=term,
                        class_number=row['reference_number'],
                        section_number=row['section_number'],
                        course=course,
                        teacher=teacher,
                        highschool=highschool,
                        start_date=start_date,
                        end_date=end_date,
                        free_period=row.get('free_period', ''),
                        period_time=row.get('period_time', ''),
                        tuition=row.get('tuition', 0) if row.get('tuition', '') != '' else 0,
                        highschool_course_name=row.get('highschool_course_title', ''),
                        status='A' if row.get('cancel_flag', '').lower() == 'n' else 'C',
                        registration_term=registration_term
                    )

                    meta = class_section.meta
                    if not meta:
                        meta = {}

                    class_section.highschool = highschool
                    class_section.save()

                    row['RESULT'] = "Success"
                    result.append(row)
                except Exception as e:
                    print(row)
                    # print('failed')
                    # # print(row)
                    print(e)
                    # return

                    continue
                # row_num += 1

        return {
            'status': 'success',
            'records': result
        }



    @staticmethod
    def import_from_csv(dictReader, use_bulk=True):
        """
        Import sections from CSV with optional bulk operations.
        
        Args:
            dictReader: CSV DictReader object
            use_bulk: If True, use bulk operations for better performance (default: True)
        
        Returns:
            Dict with 'status', 'records', and 'summary' keys
        """
        from cis.services.importers import ClassSectionImporter
        
        importer = ClassSectionImporter(
            use_bulk_operations=use_bulk,
            batch_size=500,
            use_transactions='none'
        )
        return importer.process_csv(dictReader)
    
    @staticmethod
    def update_roster_verification_from_csv(dictReader):
        '''
        Returns a list of OrderedDict with results after importing sections from 
        csv.DictReader object
        '''
        required_headers = [
            'ID',
            'Roster Status'
        ]
        has_headers = False
        result = []
        for row in dictReader:
            if not has_headers:
                missing_headers = []
                for header in required_headers:
                    if header not in row.keys():
                        missing_headers.append(header)
                if len(missing_headers) > 0:
                    return {
                        'status': 'error',
                        'message': 'Missing some required column headers, ' + ''.join(missing_headers)}
                has_headers = True

            try:
                row['Roster Status'] = row['Roster Status'].lower()
                
                class_section = ClassSection.objects.filter(
                    pk=row['ID']
                ).update(
                    roster_status=row['Roster Status']
                )

                row['RESULT'] = "Successfully updated section"
                result.append(row)
            except ClassSection.DoesNotExist:
                row['RESULT'] = 'Unable to find class section'
                result.append(row)
                continue
            except Exception as e:
                row['RESULT'] = "failed " + str(e)
                row.append(row)

        return {
            'status': 'success',
            'records': result
            }

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "class_sections.csv"
        fields = {
            'pk': 'ID',
            'term': "Term",
            "class_number": "Class No.",
            "section_number": "Section No.",
            "teacher": "Instructor",
            "teacher.user.psid": "Instructor EMPLID",
            "highschool.name": "High School",
            "course": "Course",
            "credit_hours": "Credits"
        }

        return export_to_excel(file_name, records, fields)

class ClassSectionSyllabi(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    description = models.TextField(blank=True)
    media = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=syllabus_upload_path
    )

    class_sections = models.ManyToManyField(ClassSection)

    STATUS_OPTIONS = (
        ('---', '---'),
        ('pending review', 'Pending Review'),
        ('Reviewed', 'Reviewed'),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_OPTIONS,
        default="pending review"
    )
    uploaded_on = models.DateTimeField(auto_now=True)

    @property
    def filename(self):
        return os.path.basename(self.media.name)

    @property
    def instructor_delete_url(self):
        return reverse_lazy('instructor:delete_syllabi', kwargs={
            'record_id': self.id})

    @property
    def ce_delete_url(self):
        return reverse_lazy('cis:delete_syllabi', kwargs={
            'record_id': self.id})


@receiver(models.signals.post_delete, sender=ClassSection)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    if instance.syllabi:
        instance.syllabi.delete(save=False)
        return True
    return False


def _tenant_registration_override(name):
    """Return the tenant's override for a StudentRegistration rule, or None.

    Recommendation eligibility is tenant policy: which grade levels need a
    recommendation, which terms a filed recommendation covers, and which
    registrations count as "pending" all differ per deployment. A tenant opts in
    by defining the named function in its ``services/registration.py`` (the
    module that already owns mirror_to_sis); tenants that don't get the defaults
    below unchanged.

    Imported inside the function on purpose — a tenant's services module
    imports ``cis.models.*`` at its own module level, so resolving it while
    ``cis.models.section`` is still importing would risk AppRegistryNotReady.
    """
    from cis.services.tenant_services import get_tenant_override
    return get_tenant_override('registration', name)


class StudentRegistrationQuerySet(models.QuerySet):
    def pending_sis_mirror(self, trigger_statuses=None):
        """Registrations queued for the next SIS mirror run.

        Single source of truth shared by send_registrations_to_sis and the
        Pending SIS Mirror tab. `trigger_statuses` defaults to the
        sis_mirror_trigger setting; callers that already loaded the config
        pass it in to avoid a second from_db().
        """
        if trigger_statuses is None:
            from cis.settings.registration_status_email import registration_status_email
            trigger_statuses = registration_status_email.from_db().get('sis_mirror_trigger') or []
        return self.filter(status__in=trigger_statuses, needs_mirroring=True)

    def awaiting_recommendation(self, terms=None):
        """Applied registrations whose course requires a recommendation.

        The selection half of the counselor chase-up, as a queryset so callers
        can narrow it further (by school, by student) instead of re-deriving the
        rule. `terms` scopes to the sections' registration terms; None applies
        no term scoping.

        The grade rule is `recommendation_required_q()` rather than a Python
        loop collecting skip_ids, which is one query and — unlike a bare
        `__contains` on registration_eligibility — cannot match every asterisk
        course for a student with a blank grade level.
        """
        from cis.models.student import recommendation_required_q

        qs = self.filter(status='applied').filter(recommendation_required_q())
        if terms is not None:
            qs = qs.filter(class_section__registration_term__in=terms)
        return qs


class StudentRegistration(models.Model):
    """
    Student Registration model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_on = models.DateTimeField(auto_now_add=True)

    objects = StudentRegistrationQuerySet.as_manager()

    history = HistoricalRecords()

    VERIFICATION_STATUS = (
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('not_verified', 'Not Verified'),
        ('enrolled', 'Enrolled'),
        ('not_enrolled', 'Not Enrolled')
    )
    verified_on = models.DateTimeField(auto_now_add=False, blank=True, null=True)
    verification_status = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        default='pending',
        choices=VERIFICATION_STATUS
    )

    student = models.ForeignKey('cis.Student', on_delete=models.PROTECT)
    class_section = models.ForeignKey('cis.ClassSection', on_delete=models.PROTECT)

    STATUS_OPTIONS = (
        ('applied', 'Requested'),

        # ('approved_by_instructor', 'Approved by Instructor'),
        # ('not_approved_by_instructor', 'Not Approved by Instructor'),
        
        ('approved', 'Ready for Review'),
        ('not_approved', 'Not Approved by HS'),
        ('missing_prereq', 'Missing PreReq'),

        # A registration the student entered twice. Distinct from a denial on
        # purpose: closing duplicates out as 'not_approved' misreports the
        # school's approval rate. Carried in HVCC's own tree before the
        # extraction (ewu#47).
        ('duplicate', 'Duplicate Section'),

        # ('knowledge_assessment', 'Pending Knowledge Assessment'),

        # ('cancelled', 'Cancelled'),
        # ('section_is_full', 'Section is Full'),
        # ('waitlist', 'Waitlist'),
        # ('late_application', 'Late Application'),

        ('pending_registration', 'Approved for Registration'),
        ('denied_registration', 'Not Approved for Registration'),
        ('registered', 'Registered'),
        ('enrolled', 'Enrolled'),

        ('dropped', 'Dropped'),
        ('withdrawn', 'Withdrawn'),
        ('app not processed', 'Application Not Processed-See Notes'),
    )

    highschool = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT, blank=True, null=True)

    PAY_OPTIONS = [
        ('', '---'),
        ('student', 'Student Pay'),
        ('school_full', 'School Full Pay'),
        ('school_partial', 'School Partial Pay'),
        # ('frl', 'Free or Reduced Lunch'),
    ]
    pay_type = models.CharField(
        max_length=20,
        choices=PAY_OPTIONS,
        default=''
    )
    non_student_pay_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.00
    )

    registration_type = models.CharField(
        max_length=20,
        default='aspirations',
        choices=REGISTRATION_TYPES
    )

    reviewer = models.ForeignKey(
        'cis.HSAdministrator',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    status = models.CharField(
        max_length=100,
        choices=STATUS_OPTIONS,
        default='applied'
    )
    status_changed_on = JSONField()
    note = models.TextField(
        blank=True,
        null=True,
        help_text='Note of the registration status'
    )
    grade = models.CharField(
        max_length=10,
        default='-'
    )

    tracker = FieldTracker(fields=['status'])


    REQUIRED_HEADERS = [
        'banner_id', 'term', 'crn', 'status', 'description'
    ]

    needs_mirroring = models.BooleanField(null=True, blank=True)

    sis_id = models.UUIDField(default=None, blank=True, null=True)

    # Legacy: was M2M to cis.SIS_Log but received ethos.EthosLog at runtime,
    # which raised TypeError on .add(). Replaced by mirror_logs below.
    sis_log = models.ManyToManyField('cis.SIS_Log', blank=True)

    # Per-attempt EthosLog records for SIS registration mirror calls.
    mirror_logs = models.ManyToManyField(
        'ethos.EthosLog',
        blank=True,
        related_name='student_registrations',
    )

    MIRROR_STATUS_CHOICES = [
        ('success', 'Success'),
        ('failed',  'Failed'),
        ('skipped', 'Skipped'),
    ]
    last_mirror_status = models.CharField(
        max_length=10,
        choices=MIRROR_STATUS_CHOICES,
        blank=True,
        null=True,
        db_index=True,
        help_text='Outcome of the most recent mirror_to_sis attempt',
    )
    last_mirror_error = models.TextField(blank=True, default='')
    last_mirror_at = models.DateTimeField(blank=True, null=True, db_index=True)
    
    @property
    def submitted_grade(self):
        """Display grade for this registration.

        Grade *policy* lives in the optional ``grades`` app; this delegates
        through the ``cis.integrations.grades`` shim, which returns ``'-'``
        when grades is not installed.
        """
        from cis.integrations.grades import submitted_grade

        return submitted_grade(self)

    @property
    def billed_school_cost(self):
        from django.db.models import Sum
        
        from student_transactions.models import StudentTransaction
        transactions = StudentTransaction.objects.filter(
            student=self.student,
            label='school_charge',
            meta__registration=str(self.id)
        ).aggregate(Sum('amount'))
        return transactions.get('amount__sum', 0)
    
    @property
    def pay_type_pretty(self):
        if self.pay_type:
            for k, v in self.PAY_OPTIONS:
                if k == self.pay_type:
                    if self.non_student_pay_amount > 0:
                        return mark_safe(f'{v}<br>School Paying - ${self.non_student_pay_amount}')
                    return v
        return '---'
    
    def notify_sis_mirror_fail(self, log, error_message):
        try:
            from cis.settings.registration_status_email import registration_status_email

            config = registration_status_email.from_db()

            subject = 'Canusia - Registration Send Error'
            text_body = f'{self.student.user.last_name}, {self.student.user.first_name} - {self.student.user.psid} for {self.class_section} {self.status} - {error_message}'

            html_body = text_body
            to = config.get('sis_mirror_error_notifications', 'kadaji@gmail.com').split(',')

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
        except:
            ...

    def next_step(self):
        if self.status == 'applied':
            return 'Awaiting Instructor Approval'
        
        if self.status == 'approved_by_instructor':
            return 'Pending Registration'

        if self.status == 'not_approved_by_instructor':
            return ''

        if self.status == 'registered':
            return ''
        
        return ''

    class Meta:
        unique_together = [['student', 'class_section']]

    def __str__(self):
        return f"{self.student.user.last_name}, {self.student.user.first_name} ({self.status})"


    @staticmethod
    def needs_notification(last_sent_on, num_days):
        from datetime import datetime

        current_date = datetime.now()
        last_sent_on = datetime.strptime(last_sent_on, '%m/%d/%Y')

        return True if abs((current_date - last_sent_on).days) >= num_days else False

    def instructor_actions(self, skip_check=False):
        actions = []

        actions.append(('enrolled', 'Enrolled'))
        actions.append(('not_enrolled', 'Not Enrolled'))

        sections = self.other_sections()
        for section in sections:
            actions.append(
                ('move_to_' + str(section.id), f'Move to {section}')
            )

        return actions

    def move_to_section(self, new_section_id, request):
        new_class_section = ClassSection.objects.get(pk=new_section_id)

        self.student.add_note(
            createdby=request.user,
            note=f'Moving {self.class_section} to {new_class_section}',
            meta={
                'type': 'public',
                'registration_id': str(self.id)
            }
        )

        self.class_section = new_class_section
        self.save()

        return self
    
    def pay_type_actions_sexy(self):
        from cis.utils import is_pay_type_review_open
        result = ''
        if is_pay_type_review_open():
            result = f'<select name="registration_pay_type_{self.id}"  id="id_registration_{self.id}_pay_type" data-id="{self.id}" class="form-control pay_type" data-key="{self.id}"> <option value="">Select</option><option value=\'student\'>Student Pay</option><option value=\'school_full\'>School Full Pay</option><option value=\'school_partial\'>School Partial Pay</option></select><br><input type="number" data-id="{self.id}" name="registration_non_student_pay_amount_{self.id}" id="id_registration_{self.id}_non_student_pay_amount" class="form-control d-none non_student_pay_amount" placeholder="School Paying Amount" value=""><br>'
            
        return result

    def instructor_actions_sexy(self):

        from cis.utils import is_instructor_review_open
        result = ''
        if is_instructor_review_open() and self.verification_status == 'pending':
            result = f"<select class='form-control form-control-sm mt-2 instructor_action' data-section-id='{self.class_section.id}' data-id='{self.id}' style='width: 80%'>"
            result += "<option value=''>Select</option>"
            actions = self.instructor_actions(skip_check=True)
            if actions:
                for k, v in actions:
                    result += f"<option " + ( 'selected ' if self.status == k else ' ') + f" value='{k}'>{v}</option>"
                result += "</select>"

        else:
            if self.verification_status == 'enrolled':
                result += 'Marked as Enrolled'
            elif self.verification_status == 'not_enrolled':
                result += 'Marked as Not Enrolled'
            else:
                result = self.verification_status.capitalize()

        return result

    def other_sections(self):
        return ClassSection.objects.filter(
            term=self.class_section.term,
            highschool=self.class_section.highschool,
            course=self.class_section.course
        ).exclude(
            id=self.class_section.id
        )

    @property
    def ce_url(self):
        return reverse_lazy('cis:registration', kwargs={
            'record_id': self.id})

    @property
    def sexy_status(self):
        return self.get_status
    
    @property
    def get_status(self):
        for (key, value) in self.STATUS_OPTIONS:
            if key == self.status:
                return value
        return ''

    @property
    def get_status_history(self):
        result = ''
        for key, val in self.status_changed_on.items():
            result += f'<div class="detail_label">{key}</div><div class="">{val}</div>'
        return result

    @property
    def applied_on(self):
        return self.status_changed_on['applied_on']

    @property
    def reviewed_on(self):
        if self.status == 'not_approved':
            return self.status_changed_on.get('not_approved_on', None)
        return self.status_changed_on.get('approved_on', None)

    @property
    def status_changed(self):
        changed_on = self.status_changed_on
        return changed_on.get(f'{self.status}_on')

    @property
    def has_signed_student_agreement(self):
        from cis.models.student import StudentAgreement
        return StudentAgreement.has_signed(self.student, self.class_section.term.id)

    @property
    def has_signed_student_agreement_pretty(self):
        from cis.models.student import StudentAgreement
        has_signed = StudentAgreement.has_signed(self.student, self.class_section.term.id)
        if has_signed:
            return 'Received'
        return 'Pending'

    @property
    def has_signed_parent_consent(self):
        from cis.models.student import ParentConsent
        return ParentConsent.has_signed(self.student, self.class_section.term.id)
    
    @property
    def has_signed_parent_consent_pretty(self):
        from cis.models.student import ParentConsent
        signed = ParentConsent.has_signed(self.student, self.class_section.term.id)
        return 'Received' if signed else 'Pending'

    @property
    def is_held_for_parent_consent(self):
        """True when parent consent is a required step but not yet signed.

        parent_consent is a tenant-level student_onboarding step; when the
        step is not enabled (e.g. ewu) this is always False.
        """
        from student_onboarding.step_registry import get as get_step
        parent_consent_on = get_step('parent_consent') is not None
        return bool(parent_consent_on and not self.has_signed_parent_consent)

    @classmethod
    def get_form_message(cls, setting_name='intro'):
        setting_key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_apply_classes"
        return Setting.get_value(setting_key, setting_name)

    @staticmethod
    def can_register(student, class_section):
        registrations = student.get_registrations()

        return not registrations.filter(
            class_section__term=class_section.term,
            class_section__course=class_section.course,
            status__in=['applied', 'approved_by_instructor', 'registered']
        ).exists()

    @staticmethod
    def notify_homeschool_parents(*args, **kwargs):
        from datetime import datetime

        from cis.utils import registration_terms as get_registration_terms, getDomain, upload_to_s3

        from cis.models.student import ParentConsent
        from cis.settings.registrations import registrations as registration_settings
        from cis.settings.student_regis_pending import student_regis_pending as parent_email_settings

        registration_terms = get_registration_terms()
        email_settings = registration_settings.from_db()
        parent_email_settings = parent_email_settings.from_db()

        home_school_id = email_settings.get('homeschool')

        # get all home student students who are in an applied status
        distinct_applied_registrations = StudentRegistration.objects.filter(
            status__in=['applied'],
            class_section__term__in=registration_terms,
            student__highschool__id=home_school_id
        ).distinct('student')

        from cis.utils import is_valid_email

        emails_sent = 0
        emails = []
        for registration in distinct_applied_registrations:
            student = registration.student

            to = []
            if is_valid_email(student.parent_email):
                to.append(student.parent_email)

            parent_consent_url = ParentConsent.get_url(
                student.id,
                registration.class_section.term.id
            )

            subject = parent_email_settings.get('homeschool_subject', 'Customize in settings')
            message = Template(parent_email_settings.get('homeschool_email', 'change'))
            context = Context({
                'student_first_name': student.user.first_name,
                'student_last_name': student.user.last_name,
                'parent_first_name': student.parent_first_name,
                'parent_consent_url': parent_consent_url
            })

            text_body = message.render(context)

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            is_active = email_settings.get('is_active', 'No')
            if getattr(settings, 'DEBUG', True) or is_active == 'Debug':
                to = ['kadaji@gmail.com']
            elif is_active == 'No':
                continue

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
            
            emails.append(
                {
                    'to': to,
                    'message': text_body
                }
            )
            emails_sent += 1

        prefix = getattr(
            settings,
            'CAMPUS_CODE_PREFIX'
        )
        upload_to_s3(
            json.dumps(emails),
            f'{prefix}/email/daily/registration/homeschool/summary'
        )

        logger.info(f'Sent {emails_sent} emails to home school parent')
        logger.error(f'Sent {emails_sent} emails to home school parent')



    @staticmethod
    def counselor_notification_groups(terms=None):
        """Who to chase for recommendations, grouped by the school to email.

        The selection half of `notify_school_counselors`: which registrations
        are outstanding, which school each belongs to, and who at that school
        hears about it. All three are tenant policy — the send half (settings
        gating, template rendering, delivery, note-keeping) stays in cis.

        Returns a list of dicts with keys `highschool`, `registrations` (one row
        per student) and `recipients` (a list of email addresses). Tenants
        override by defining `counselor_notification_groups(terms=None)` in
        their services/registration.py.

        `terms` defaults to the configured registration terms.
        """
        override = _tenant_registration_override('counselor_notification_groups')
        if override is not None:
            return override(terms=terms)

        from cis.models.highschool import HighSchool
        from cis.utils import registration_terms as get_registration_terms

        if terms is None:
            terms = get_registration_terms() or []

        applied_registrations = StudentRegistration.objects.awaiting_recommendation(
            terms=terms)

        # Preserved verbatim, quirk included: DISTINCT ON the *student's* school
        # while selecting the *section's* school, so only one section-school
        # survives per student-school and the rest are never notified. Changing
        # it here would change behaviour for every tenant on a release meant to
        # be a refactor; ewu's override regroups by the student's school, which
        # is the school that owns the recommendation.
        highschool_ids = applied_registrations.distinct(
            'student__highschool__id').values_list(
                'class_section__highschool',
                flat=True
            )

        groups = []
        for highschool_id in list(set(highschool_ids)):
            highschool = HighSchool.objects.get(
                pk=highschool_id
            )

            hs_administrators = highschool.administrators_in_highschool(
                'can_manage_student_recommendation')

            groups.append({
                'highschool': highschool,
                'registrations': applied_registrations.filter(
                    class_section__highschool=highschool
                ).distinct('student'),
                'recipients': [
                    member.user.email for member in hs_administrators
                ],
            })
        return groups

    @staticmethod
    def notify_school_counselors(*args, **kwargs):
        from cis.settings.school_counselor_regis_email import school_counselor_regis_email

        email_settings = school_counselor_regis_email.from_db()

        is_active = email_settings.get('is_active', 'No')
        if is_active == 'No':
            return

        emails_sent = 0

        for group in StudentRegistration.counselor_notification_groups():
            students = []
            for registration in group['registrations']:
                students.append(
                    f'{registration.student.user.first_name} {registration.student.user.last_name}'
                )

                registration.student.add_note(None, 'Emailed school counselor requesting recommendation')

            students.sort()

            to = group['recipients']

            subject = email_settings.get('pending_rec_email_subject', 'Customize in settings')
            message = Template(email_settings.get('pending_rec_email'))
            context = Context({
                'student_list': mark_safe('<br>'.join(students))
            })

            text_body = message.render(context)

            template = get_template('cis/email.html')
            html_body = template.render({
                'message': text_body
            })

            is_active = email_settings.get('is_active', 'No')           
            if is_active == 'Debug':
                to = email_settings.get('debug_email_list').split(',')
            elif is_active == 'No':
                continue

            send_html_mail(
                subject,
                text_body,
                html_body,
                settings.DEFAULT_FROM_EMAIL,
                to
            )
            
            emails_sent += 1

    def get_email_template(self):
        """
        Returns a tuple of subject, message for current registration status
        """
        from ..settings.registration_status_email import registration_status_email
        email_settings = registration_status_email.from_db()
        
        return (
            email_settings.get(f'status_change_{self.status}_subject'),
            email_settings.get(f'status_change_{self.status}_email')
        )


    def get_recommendation(self):
        from cis.models.student import StudentRecommendation
        try:
            record = StudentRecommendation.objects.get(
                student=self.student,
                term=self.class_section.term
            )
            return record
        except StudentRecommendation.DoesNotExist:
            return None

    def get_student_signature(self):
        from cis.models.student import StudentAgreement
        try:
            record = StudentAgreement.objects.get(
                student=self.student,
                term=self.class_section.term
            )
            return record
        except StudentAgreement.DoesNotExist:
            return None

    def get_parent_consent(self):
        from cis.models.student import ParentConsent
        try:
            record = ParentConsent.objects.get(
                student=self.student,
                term=self.class_section.term
            )
            return record
        except ParentConsent.DoesNotExist:
            return None

    @classmethod
    def remove_registration(student, registration):
        pass

    @staticmethod
    def reset_registrations(terms=[]):
        """
        Reset all registrations for terms. 

        This method is called prior to each registration import
        """
        if terms:
            StudentRegistration.objects.filter(
                class_section__term__in=terms
            ).all().delete()

    @staticmethod
    def import_from_csv(dictReader):

        from cis.models.term import Term
        from cis.models.student import Student
        """
        """
        required_headers = StudentRegistration.REQUIRED_HEADERS
        has_headers = False
        result = []
        for row in dictReader:
            if not has_headers:
                missing_headers = []
                for header in required_headers:
                    if header not in row.keys():
                        missing_headers.append(header)
                if len(missing_headers) > 0:
                    return {
                        'status': 'error',
                        'message': 'Missing some required column headers, ' + ','.join(missing_headers)}
                has_headers = True
            # Check if term exists
            try:
                term = Term.objects.get(
                    code__iexact=row['term']
                )
            except Term.DoesNotExist:
                row['RESULT'] = 'Unable to find term code'
                result.append(row)
                continue
            
            # Check if student exists
            try:
                student = Student.objects.get(
                    user__psid=row['banner_id']
                )
            except Student.DoesNotExist:
                row['RESULT'] = 'Unable to find student record'
                result.append(row)
                continue

            # Check if CRN for term exists
            try:
                class_section = ClassSection.objects.get(
                    term=term,
                    class_number=row['crn']
                )
            except ClassSection.DoesNotExist:
                row['RESULT'] = 'Unable to find CRN for term'
                result.append(row)
                continue

            try:
                registration = StudentRegistration.objects.get(
                    student=student,
                    class_section=class_section
                )
            except StudentRegistration.DoesNotExist:
                registration = StudentRegistration()

            registration.student = student
            registration.highschool = student.highschool
            registration.class_section = class_section
            registration.status = row['status']
            registration.note = row['description']

            try:
                registration.save()
            except Exception as e:
                print(e)
                row['RESULT'] = "Unable to save registration " + str(e)
                result.append(row)
                continue

            row['RESULT'] = "Successfully saved registration"
            result.append(row)

        return {
            'status': 'success',
            'records': result}

    def charges(self):
        from student_transactions.models import StudentTransaction
        charges = StudentTransaction.objects.filter(
            meta__registration=str(self.id)
        )
        return charges
    
    def charges_asHTML(self):
        charges = self.charges()

        if charges.count() == 0:
            return "<p>No charges found for this registration.</p>"
        
        result = "<table class='table table-bordered table-striped'>"
        result += "<thead><tr><th>Charge</th><th>Amount</th></tr></thead><tbody>"
        for charge in charges:
            result += f"<tr><td>{charge.description}</td><td>${charge.amount}</td></tr>"
        result += "</tbody></table>"

        return result

    def asHTML(self):
        from cis.settings.registration_profile import (
            registration_profile, REGISTRATION_DEFAULT_DISPLAY,
        )
        from cis.utils import resolve_display_layout

        raw = registration_profile.from_db().get('profile_display')
        layout = resolve_display_layout(raw, REGISTRATION_DEFAULT_DISPLAY)
        return model_as_HTML(self, layout)

    def needs_recommendation(self):
        """Whether this registration's course requires a recommendation.

        Tenants may override by defining ``needs_recommendation(registration)``
        in their ``services/registration.py``.
        """
        override = _tenant_registration_override('needs_recommendation')
        if override is not None:
            return override(self)

        grade_level = self.student.grade_level
        eligibility = self.class_section.course.registration_eligibility

        return f'{grade_level}*' in eligibility
    
    def has_recommendation(self):
        """Whether a recommendation already exists for this registration.

        Tenants may override by defining ``has_recommendation(registration)``
        in their ``services/registration.py`` — which terms count as covering a
        registration is tenant policy.
        """
        override = _tenant_registration_override('has_recommendation')
        if override is not None:
            return override(self)

        from django.db.models import Q
        from cis.models.student import StudentRecommendation
        return StudentRecommendation.objects.filter(
            Q(student=self.student) & 
            (Q(term=self.class_section.registration_term) | Q(term=self.class_section.term))
        ).exists()
    
    @classmethod
    def get_pending_recommendations(cls, student_ids=None, highschool_ids=None):
        """
        Returns a queryset of 'StudentRegistration' where reviewer is 'None'.

        Tenants may override by defining
        ``get_pending_recommendations(student_ids=None, highschool_ids=None)``
        in their ``services/registration.py``.
        """
        override = _tenant_registration_override('get_pending_recommendations')
        if override is not None:
            return override(
                student_ids=student_ids, highschool_ids=highschool_ids)

        # No scope means no results. Callers pass the ids they are allowed to
        # see, so an unscoped call must stay empty rather than falling through
        # to every pending recommendation in the deployment.
        if not student_ids and not highschool_ids:
            return StudentRegistration.objects.none()

        # `reviewer is None` is the definition of "pending" and belongs to both
        # branches. It used to sit only on the student_ids branch, so a
        # registration that had been reviewed but whose status was still
        # 'applied' kept counting as pending for the high-school dashboard,
        # tab, and API — the two branches answered different questions under
        # one name.
        records = StudentRegistration.objects.filter(reviewer__isnull=True)

        # Each argument NARROWS the queryset. Reassigning instead meant that
        # passing both silently discarded student_ids and returned every
        # pending registration at those schools, for all students — a strictly
        # wider set than the caller asked for, with no error.
        if student_ids:
            records = records.filter(student__id__in=student_ids)

        if highschool_ids:
            # Scope by the STUDENT's high school, not the section's host high
            # school. The recommendation belongs to the school the student
            # attends; those differ whenever a student takes a section hosted
            # elsewhere, and filtering on the section's school surfaced pending
            # work to admins who hold no recommendation permission for that
            # student.
            records = records.filter(
                status__in=['applied'],
                student__highschool__id__in=highschool_ids
            )

            # The eligibility test reads `student.grade_level` and
            # `course.registration_eligibility` per row. select_related pulls
            # both in the same query, so this is two queries regardless of row
            # count rather than one per row plus one.
            records = records.select_related('student', 'class_section__course')
            skip_ids = [
                record.id for record in records
                if f'{record.student.grade_level}*' not in
                (record.class_section.course.registration_eligibility or '')
            ]
            if skip_ids:
                records = records.exclude(id__in=skip_ids)

        return records

class StudentDropRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_on = models.DateTimeField(auto_now_add=True)

    student = models.ForeignKey('cis.Student', on_delete=models.CASCADE)
    registration = models.ForeignKey('cis.StudentRegistration', on_delete=models.CASCADE)

    STATUS_OPTIONS = (
        ('requested', 'Requested'),
        ('processed', 'Processed')
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_OPTIONS,
        default='requested'
    )

    tracker = FieldTracker(fields=['status'])
    status_changed_on = JSONField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)

    def asHTML(self):
        format = [
            [
                'student.user.first_name',
                'student.user.last_name'
            ],
            [
                'student.highschool.name'
            ],
            [
                'note'
            ]
        ]
        drop_req = model_as_HTML(self, format)
        drop_req += self.registration.asHTML()
        return drop_req

    @property
    def ce_url(self):
        return reverse_lazy('cis:drop_wd_req', kwargs={
            'record_id': self.id})

    @classmethod
    def get_form_message(cls, setting_name='intro'):
        setting_key = getattr(settings, 'CAMPUS_CODE_PREFIX')+"_drop_req"
        return Setting.get_value(setting_key, setting_name)

    @classmethod
    def exists(cls, student_id, registration_id):
        return StudentDropRequest.objects.filter(
            student__id=student_id,
            registration__id=registration_id).exists()

    @classmethod
    def add_new(cls, student_id, registration_id, note, status='requested'):
        from ..models.student import Student

        if not StudentDropRequest.exists(
                student_id,
                registration_id
        ):
            request = StudentDropRequest()
            request.student = Student.objects.get(pk=student_id)
            request.registration = StudentRegistration.objects.get(pk=registration_id)
            request.note = note
            request.status = status

            request.save()
            return request

        return None


