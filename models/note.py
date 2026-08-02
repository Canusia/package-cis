# users/models.py
import uuid
from django.conf import settings

from django.db import models
from django.db.models import JSONField
from django.urls import reverse_lazy
from django.utils.safestring import mark_safe

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.contrib.sites.models import Site

from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from mailer import send_mail, send_html_mail

from cis.utils import (
    student_notes_media_upload_path,
    teacher_notes_media_upload_path,
    send_sms
)

from cis.storage_backend import PrivateMediaStorage

from cis.settings.student_notes_email import (
    student_notes_email 
)

from cis.settings.notes_email import notes_email

class Note(models.Model):
    """
    Note model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    note = models.TextField(blank=False)

    createdby = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)
    createdon = models.DateTimeField(auto_now=True)

    parent = models.UUIDField(blank=True, null=True)

    class Meta:
        abstract = True

class ClassSectionNote(Note, models.Model):
    """
    Notes for Class Section
    """
    class_section = models.ForeignKey(
        'cis.ClassSection',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    meta = JSONField(blank=True, null=True)
    class Meta:
        ordering = ['createdon']

    @property
    def sexy_note(self):
        return mark_safe(self.note)

    @classmethod
    def add_note(cls, request, note_form):
        from cis.models.section import ClassSection
        note = cls()
        data = note_form.cleaned_data

        note.class_section = ClassSection.objects.get(
            pk=note_form.cleaned_data['add_to'])
        note.createdby = request.user
        note.note = note_form.cleaned_data['note']

        meta = {}
        if data.get('type'):
            meta['type'] = data.get('type')
        else:
            meta['type'] = 'private'

        note.meta = meta
        note.save()
        return note


class ClassVisitReportNote(Note, models.Model):
    """
    Notes for Class Section Visit Report
    """
    visit_report = models.ForeignKey(
        'class_visit.VisitReport',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    meta = JSONField(blank=True, null=True)
    class Meta:
        ordering = ['createdon']

    @classmethod
    def add_note(cls, request, note_form):
        from class_visit.models import VisitReport
        note = cls()
        data = note_form.cleaned_data

        note.visit_report = VisitReport.objects.get(
            pk=note_form.cleaned_data['add_to']
        )
        note.createdby = request.user
        note.note = note_form.cleaned_data['note']

        meta = {}
        if data.get('type'):
            meta['type'] = data.get('type')
        else:
            meta['type'] = 'private'

        note.meta = meta
        note.save()
        return note

class FacultyCoordinatorNote(Note, models.Model):
    """
    Notes for Course
    """
    faculty_coordinator = models.ForeignKey(
        'cis.FacultyCoordinator',
        on_delete=models.PROTECT
    )

    class Meta:
        ordering = ['createdon']

    @classmethod
    def add_note(cls, request, note_form):
        from cis.models.course import Course

        note = cls()
        note.course = Course.objects.get(
            pk=note_form.cleaned_data['add_to']
        )
        note.createdby = request.user
        note.note = note_form.cleaned_data['note']
        note.save()
        return note

class CourseNote(Note, models.Model):
    """
    Notes for Course
    """
    course = models.ForeignKey(
        'cis.Course',
        on_delete=models.PROTECT
    )

    class Meta:
        ordering = ['createdon']

    @classmethod
    def add_note(cls, request, note_form):
        from cis.models.course import Course

        note = cls()
        note.course = Course.objects.get(
            pk=note_form.cleaned_data['add_to']
        )
        note.createdby = request.user
        note.note = note_form.cleaned_data['note']
        note.save()
        return note

class HighSchoolNote(Note, models.Model):
    """
    Notes for HighSchool
    """
    highschool = models.ForeignKey(
        'cis.HighSchool',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    class Meta:
        ordering = ['createdon']

    @classmethod
    def add_note(cls, request, note_form):
        from cis.models.highschool import HighSchool

        note = cls()
        note.highschool = HighSchool.objects.get(
            pk=note_form.cleaned_data['add_to'])
        note.createdby = request.user
        note.note = note_form.cleaned_data['note']
        note.save()
        return note

class HSAdministratorNote(Note, models.Model):
    """
    Notes for HS Administrator
    """
    hsadmin = models.ForeignKey(
        'cis.HSAdministrator',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    class Meta:
        ordering = ['createdon']

    @classmethod
    def add_note(cls, request, note_form):
        from cis.models.highschool_administrator import HSAdministrator

        note = cls()
        note.hsadmin = HSAdministrator.objects.get(
            pk=note_form.cleaned_data['add_to'])
        note.createdby = request.user
        note.note = note_form.cleaned_data['note']
        note.save()
        return note

class TeacherNote(Note, models.Model):
    teacher = models.ForeignKey(
        'cis.Teacher',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    meta = JSONField(blank=True, null=True)

    media = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=teacher_notes_media_upload_path,
        blank=True,
        null=True
    )
    
    class Meta:
        ordering = ['createdon']

    def send_as_email(self):
        email_settings = notes_email.from_db()      
        
        subject = email_settings.get('note_to_instructor_subject')
        message = Template(email_settings.get('note_to_instructor_email'))

        context = Context({
            'instructor_first_name': self.teacher.user.first_name,
            'instructor_last_name': self.teacher.user.last_name,
            'note': mark_safe(self.note),
            'created_by_first_name': self.createdby.first_name,
            'created_by_last_name': self.createdby.last_name,
            'created_by_email': self.createdby.email,
        })
        text_body = message.render(context)

        to = [self.teacher.user.email]
        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )


    @classmethod
    def add_note(cls, request, note_form):
        from cis.models.teacher import Teacher
        data = note_form.cleaned_data

        note = cls()
        note.teacher = Teacher.objects.get(
            pk=note_form.cleaned_data['add_to'])
        note.createdby = request.user
        note.note = note_form.cleaned_data['note']

        meta = {}
        if data.get('type'):
            meta['type'] = data.get('type')
        else:
            meta['type'] = ['private']

        if data['reply_to']:
            note.parent = data['reply_to']
            meta['type'] = 'response'

        note.meta = meta
        
        if request.FILES:
            note.media = request.FILES['media']

        note.save()
        return note

class StudentNote(Note, models.Model):
    student = models.ForeignKey(
        'cis.Student',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    media = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=student_notes_media_upload_path,
        blank=True,
        null=True
    )
    
    meta = JSONField(blank=True, null=True, default=dict)
    class Meta:
        ordering = ['-createdon']

    def send_to_parent(self):
        email_settings = student_notes_email.from_db()      
        if email_settings.get('is_active', 'No') == 'No':
            return

        subject = email_settings.get('student_note_parent_subject')
        message = Template(email_settings.get('student_note_parent_message'))

        context = Context({
            'student_first_name': self.student.user.first_name,
            'student_last_name': self.student.user.last_name,
            'note': mark_safe(self.note),
            'parent_first_name': self.student.parent_first_name,
            'parent_last_name': self.student.parent_last_name,
            'created_by_first_name': self.createdby.first_name,
            'created_by_last_name': self.createdby.last_name,
            'created_by_email': self.createdby.email,
        })
        text_body = message.render(context)

        to = [self.student.parent_email]
        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )

    def send_as_sms(self):
        to = self.student.cellphone
        message = self.note
        
        return send_sms(to, message)

    def send_to_student(self):
        email_settings = student_notes_email.from_db()      
        if email_settings.get('is_active', 'No') == 'No':
            return

        subject = email_settings.get('student_note_subject')
        message = Template(email_settings.get('student_note_message'))

        context = Context({
            'student_first_name': self.student.user.first_name,
            'student_last_name': self.student.user.last_name,
            'note': mark_safe(self.note),
            'created_by_first_name': self.createdby.first_name,
            'created_by_last_name': self.createdby.last_name,
            'created_by_email': self.createdby.email,
        })
        text_body = message.render(context)

        to = [self.student.user.email]
        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )

    @classmethod
    def add_note(cls, request, note_form):
        from cis.models.student import Student
        data = note_form.cleaned_data

        note = cls()
        note.student = Student.objects.get(
            pk=data['add_to']
        )
        note.createdby = request.user
        note.note = data['note']

        meta = {}
        if data.get('type'):
            meta['type'] = data.get('type')
        else:
            meta['type'] = ['private']

        if data['reply_to']:
            note.parent = data['reply_to']
            meta['type'] = 'response'

        note.meta = meta
        
        if request.FILES:
            note.media = request.FILES['media']

        note.save()
        return note


class TeacherApplicationNote(Note, models.Model):
    teacher_application = models.ForeignKey(
        'cis.TeacherApplication',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    meta = JSONField(blank=True, null=True)
    class Meta:
        ordering = ['-createdon']

    @classmethod
    def add_note(cls, request, note_form):
        from cis.models.teacher_applicant import TeacherApplication

        note = cls()
        data = note_form.cleaned_data

        note.teacher_application = TeacherApplication.objects.get(
            pk=data['add_to'])
        note.createdby = request.user
        note.note = data['note']

        meta = {}
        if data.get('type'):
            meta['type'] = data.get('type')
        else:
            meta['type'] = 'private'

        if data.get('reply_to'):
            note.parent = data.get('reply_to')

        note.meta = meta
        note.save()

        return note

    @property
    def teacher_reply_url(self):
        from ..utils import getDomain
        url = reverse_lazy(
                'cis:teacher_app_note_reply',
                kwargs={
                    'note_id': self.parent if self.parent else self.id 
                }
            )
        url = getDomain() + str(url)
        return url

class EventNote(Note, models.Model):
    event = models.ForeignKey(
        'pd_event.Event',
        on_delete=models.PROTECT,
        blank=True,
        null=True)

    class Meta:
        ordering = ['-createdon']

    @classmethod
    def add_note(cls, request, note_form):
        from pd_event.models import Event

        note = cls()
        note.event = Event.objects.get(
            pk=note_form.cleaned_data['add_to'])
        note.createdby = request.user
        note.note = note_form.cleaned_data['note']
        note.save()

        return note