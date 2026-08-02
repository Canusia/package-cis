# users/models.py
import datetime
import uuid

from django.utils import timezone

from django.db import models
from django.dispatch import receiver
from django.urls import reverse_lazy
from django.contrib.auth.models import Group

from django.urls import reverse_lazy
from cis.utils import (
    export_to_excel, format_emplid,
    teacher_files_upload_path
)

from cis.models.customuser import CustomUser
from cis.models.note import TeacherNote

from cis.storage_backend import PrivateMediaStorage

class Teacher(models.Model):
    """
    Base user model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)

    STATUS_OPTIONS = [
        ('active', 'Active'),
        # ('applicant', 'Applicant'),
        ('inactive', 'Inactive'),
        ('do_not_contact', 'Do Not Contact'),
        ('retired', 'Retired'),
    ]
    status = models.CharField(max_length=100, choices=STATUS_OPTIONS, default='Active')

    orientation_date = models.DateField(blank=True, null=True)
    orientation_note = models.TextField(blank=True)

    temp_id = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.last_name}, {self.user.first_name}"

    class Meta:
        ordering = ['user__last_name']

    @property
    def ce_url(self):
        return reverse_lazy('cis:instructor', kwargs={
            'record_id': self.id})

    @property
    def faculty_url(self):
        return reverse_lazy('faculty:teacher', kwargs={
            'record_id': self.id})
    
    @property
    def active_courses(self):
        return TeacherCourseCertificate.objects.filter(
            # status__iexact='active',
            teacher_highschool__teacher=self
        ).order_by('course__name')

    @property
    def active_highschools(self):
        return TeacherHighSchool.objects.filter(
            teacher=self,
            status__iexact='in the program'
        ).values_list('highschool__name', flat=True)
    
    @property
    def active_highschool_codes(self):
        return TeacherHighSchool.objects.filter(
            teacher=self,
            status__iexact='in the program'
        ).values_list('highschool__sau', flat=True)

    @staticmethod
    def delete_record(record):

        from cis.models.section import StudentRegistration, ClassSection


        if StudentRegistration.objects.filter(
            class_section__teacher=record
        ).exists():
            raise ValueError()

        ClassSection.objects.filter(
            teacher=record
        ).delete()

        TeacherCourseCertificate.objects.filter(
            teacher_highschool__teacher=record
        ).delete()

        TeacherHighSchool.objects.filter(
            teacher=record
        ).delete()

        TeacherNote.objects.filter(
            teacher=record
        ).delete()
        
        TeacherUpload.objects.filter(
            teacher=record
        ).delete()
        
        user = record.user
        record.delete()

        # try to remove base user account if this was the only role
        try:
            user.delete()
        except:
            pass

        return True

    def add_note(self, createdby, note, **kwargs):
        note = TeacherNote(
            createdby=createdby,
            note=note,
            meta={
                'type': ['private']
            },
            teacher=self
        )

        note.save()
        return note

    @classmethod
    def add_or_update(cls, psid, **kwargs):
        psid = format_emplid(psid)

        try:
            record = Teacher.objects.get(
                user__psid=psid
            )

            try:
                # Add extra fields if present
                for key, value in kwargs.items():
                    setattr(record, key, value)
            except Exception as e:
                print(e)
                pass

            
            try:
                # Add extra fields if present
                for key, value in kwargs.items():
                    setattr(record.user, key, value)
                
                record.user.save()
            except Exception as e:
                print(e)
                pass

            record.save()
        except Teacher.DoesNotExist:
            first_name = kwargs.get('first_name', '')
            last_name = kwargs.get('last_name', '')

            kwargs['psid'] = psid
            email = kwargs.get('email')
            
            username = email
            if kwargs.get('username'):
                username = kwargs.get('username')
                del kwargs['username']

            user = CustomUser.get_or_add(
                username=username,
                email=email,
                **kwargs
            )
            try:
                record = Teacher(user=user)

                record.status = kwargs.get('status')
                record.orientation_date = kwargs.get('orientation_date')
                record.orientation_note = kwargs.get('orientation_note')
                record.temp_id = psid
                
                record.save()

                group = Group.objects.get(name='instructor')
                record.user.groups.add(group)
            except:
                return None
        return record

    @classmethod
    def get_or_add(cls, psid, email, **kwargs):
        
        try:
            if not psid:
                record = Teacher.objects.get(
                    user__secondary_email__iexact=email
                )
            else:    
                record = Teacher.objects.get(
                    user__psid=psid
                )
            return record
        except Teacher.DoesNotExist:
            first_name = kwargs.get('first_name', '')
            last_name = kwargs.get('last_name', '')

            username = email
            if kwargs.get('username'):
                username = kwargs.get('username')
                del kwargs['username']

            if psid:
                kwargs['psid'] = psid
                
            user = CustomUser.get_or_add(
                username=username,
                email=email,
                **kwargs
            )
            try:
                record = Teacher(user=user)
                record.save()

                group = Group.objects.get(name='instructor')
                record.user.groups.add(group)
            except:
                return None
        return record

    @classmethod
    def add_new(cls, psid, full_name, email):
        """
        Returns a Teacher object if matching psid is found, otherwise creates a new record
        """
        try:
            user = CustomUser.objects.get(psid=psid)
        except CustomUser.DoesNotExist:
            user = CustomUser()

        user.first_name = full_name
        user.psid = psid
        user.email = email
        user.username = email.lower()
        user.save()

        try:
            teacher = Teacher.objects.get(user__psid=psid)
        except Teacher.DoesNotExist:
            teacher = Teacher()

        teacher.user = user
        teacher.save()

        group = Group.objects.get(name='instructor')
        teacher.user.groups.add(group)

        return teacher

    @staticmethod
    def import_from_csv(dictReader):
        """Import instructors from a csv.DictReader. Returns
        {status, records, summary}. See cis/services/importers/."""
        from cis.services.importers import InstructorImporter
        return InstructorImporter().process_csv(dictReader)

    @staticmethod
    def get_highschools(teacher):
        return TeacherHighSchool.objects.filter(teacher=teacher)

    def get_course_certificates(
            self,
            return_type="queryset",
            status=['Teaching'],
            highschool_ids=None):
        """
        Returns a queryset or Exports 'TeacherCourseCertificate' for 'teacher'. 
        By default only certificates in 'Approved, Certified and Contingent' 
        status will be returned
        """
        
        records = TeacherCourseCertificate.objects.filter(
            teacher_highschool__teacher=self.id,
            status__in=status
        )

        if highschool_ids:
            records = records.filter(
                teacher_highschool__highschool__id__in=highschool_ids
            )

        if return_type == "queryset":
            return records

        if return_type == "excel":
            file_name = "instructor_courses.csv"
            fields = {
                'course.cohort.designator': "Course",
                "course.catalog_number": "Catalog Number",
                "course.title": "Title",
                "course.department.name": "Department",
                "course.cohort.name": "Cohort",
                "course.credit_hours": 'Credit Hours',
                "teacher_highschool.teacher.user.first_name": "First Name",
                "teacher_highschool.teacher.user.last_name": "Last Name",
                "teacher_highschool.teacher.user.email": 'Email',
                "status": "Status",
                "teacher_highschool.since": "Since",
                "teacher_highschool.highschool.name": "High School"
            }
            return export_to_excel(file_name, records, fields)

        return None

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "instructors.csv"
        fields = {
            'user.first_name': "First Name",
            "user.last_name": "Last Name",
            "user.psid": "PSID",
            "user.email": "EMail",
            "user.alt_email": "Alt Email",
            "user.primary_phone": "Primary Phone",
            "temp_id": "TempID"
        }

        return export_to_excel(file_name, records, fields)

class TeacherHighSchool(models.Model):
    """
    Model to associate teacher with high schools
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    teacher = models.ForeignKey('cis.Teacher', on_delete=models.PROTECT)
    highschool = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT)

    STATUS_OPTIONS = [
        ('In the Program', 'In the Program'),
        ('Not in the Program', 'Not in the Program'),
    ]
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default="In the Program")
    
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        #if self._state.adding is True
        group = Group.objects.get(name='instructor')
        self.teacher.user.groups.add(group)

    def __str__(self):
        return f"{self.highschool.name} ({self.status})"

    class Meta:
        unique_together = (('teacher', 'highschool'))
        ordering = ['highschool__name']

class TeacherUpload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    teacher = models.ForeignKey('cis.Teacher', on_delete=models.PROTECT)

    MEDIA_TYPE = (
        ('Resume', 'Resume'),
        ('Transcript', 'Transcript'),
        ('CV', 'CV'),
        ('Cover', 'Cover'),
        ('Certificate', 'Certificate'),
        ('PD Letter', 'PD Letter'),
        ('Other', 'Other'),
    )
    media_type = models.CharField(
        max_length=30,
        choices=MEDIA_TYPE,
        default='Transcript'
    )

    description = models.TextField(blank=True)
    media = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=teacher_files_upload_path
    )

    uploaded_on = models.DateTimeField(auto_now=True)

    @property
    def file_name(self):
        import os
        return os.path.basename(self.media.name)

@receiver(models.signals.post_delete, sender=TeacherUpload)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    if instance.media:
        instance.media.delete(save=False)
        return True
    return False

class TeacherCourseCertificate(models.Model):
    """
    This model will have teacher's course certificates by high school.    
    """
    certificate_id = models.UUIDField(primary_key=False, blank=True, default=uuid.uuid4, editable=False)
    teacher_highschool = models.ForeignKey('cis.TeacherHighSchool', on_delete=models.CASCADE)
    course = models.ForeignKey('cis.Course', on_delete=models.PROTECT)

    STATUS_OPTIONS = [
        ('Inactive', 'Inactive'),
        ('Teaching', 'Teaching'),
        ('Applicant', 'Applicant'),
        ('Teaching Substitute', 'Teaching Substitute'),
        ('Teaching Provisional', 'Teaching Provisional'),
        ('Do Not Contact', 'Do Not Contact'),
    ]
    status = models.CharField(max_length=300, choices=STATUS_OPTIONS, default='Teaching')
    highschool_course_name = models.CharField(
        max_length=300, blank=True, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)

    since = models.DateTimeField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)

    # --- Credential expiry / renewal tracking ---
    expires_on = models.DateField(blank=True, null=True)
    renewal_required_by = models.DateField(blank=True, null=True)
    last_renewed_on = models.DateField(blank=True, null=True)
    # Reminder-dedup bookkeeping; not user-facing.
    last_reminder_sent_on = models.DateField(blank=True, null=True)

    @property
    def sexy_status(self):
        for k, v in self.STATUS_OPTIONS:
            if k == self.status:
                return v
        return ''

    @property
    def renewal_due_date(self):
        """Single source of truth for "when is this credential due".

        Prefers the explicit renewal_required_by; falls back to the hard
        expires_on. Returns None when neither is set.
        """
        return self.renewal_required_by or self.expires_on

    def is_expiring_within(self, days):
        """True when renewal_due_date is set, not past, and within `days`."""
        due = self.renewal_due_date
        if not due:
            return False
        today = timezone.localdate()
        return today <= due <= today + datetime.timedelta(days=int(days))

    @classmethod
    def due_within_q(cls, days):
        """Q filter selecting certificates whose renewal_due_date is within
        `days` of today (inclusive), where renewal_due_date = renewal_required_by
        if set else expires_on. DB-level equivalent of the renewal_due_date
        property + is_expiring_within, for use in querysets.
        """
        from django.db.models import Q
        today = timezone.localdate()
        horizon = today + datetime.timedelta(days=int(days))
        return (
            Q(renewal_required_by__isnull=False,
              renewal_required_by__gte=today, renewal_required_by__lte=horizon)
            |
            Q(renewal_required_by__isnull=True,
              expires_on__isnull=False,
              expires_on__gte=today, expires_on__lte=horizon)
        )

    @staticmethod
    def get_instructors_for_course(course):
        """
        Returns a queryset of 'TeacherCourseCertificate' who have been certified for 'course'
        """
        return TeacherCourseCertificate.objects.filter(course=course)

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "course_instructors.csv"
        fields = {
            "course.cohort.designator": "Course Name",
            "course.catalog_number": "Catalog No.",
            "status": "Status",
            "created_at": "CreatedAt",
            "since": "Since",
            "teacher_highschool.teacher.user.first_name": 'First Name',
            "teacher_highschool.teacher.user.last_name": 'Last Name',
            "teacher_highschool.teacher.user.email": 'Email',
            "teacher_highschool.highschool.name": 'High School'
        }

        return export_to_excel(file_name, records, fields)

    class Meta:
        unique_together = (('course','teacher_highschool'))
