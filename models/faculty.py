# models/faculty.py

import uuid, csv

from django.urls import reverse_lazy
from django.db import models
from django.contrib.auth.models import Group

from cis.models.customuser import CustomUser
from cis.models.note import FacultyCoordinatorNote
from cis.models.course import Department, CourseAdministrator
from cis.utils import export_to_excel

class FacultyCoordinator(models.Model):

    """
    This is not used any more
    Base user model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)
    department = models.ForeignKey('cis.Department', on_delete=models.PROTECT, blank=True, null=True)

    STATUS_OPTIONS = [
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS, default='Active')

    ASST_OPTIONS = (
        ('Yes', 'Yes'),
        ('No', 'No'),
    )
    fac_assistant = models.CharField(max_length=10, choices=ASST_OPTIONS, default='No')
    title = models.CharField(max_length=100, blank=True, null=True)
    job_title = models.CharField(max_length=100, blank=True, null=True)

    temp_id = models.IntegerField(blank=True, null=True)

    # Look through access db to see other fields
    def __str__(self):
        return self.user.first_name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        #if self._state.adding is True
        group = Group.objects.get(name='faculty')
        self.user.groups.add(group)


    @classmethod
    def get_or_add(cls, email, **kwargs):
        try:
            record = FacultyCoordinator.objects.get(
                user__email=email
            )
            return record
        except FacultyCoordinator.DoesNotExist:
            username = email
            if kwargs.get('username'):
                username = kwargs.get('username')
                del kwargs['username']

            # kwargs['psid'] = psid
            user = CustomUser.get_or_add(
                username=username,
                email=email,
                **kwargs
            )
            try:
                record = FacultyCoordinator(user=user)

                for key, value in kwargs.items():
                    setattr(record, key, value)
                record.save()
            except:
                return None
        return record

    @classmethod
    def courses_overseeing(cls, user, status='active'):
        records = CourseAdministrator.objects.filter(
            user=user,
            status__iexact='active'
        )
        return records

    def add_note(self, createdby, note, **kwargs):
        note = FacultyCoordinatorNote(
            createdby=createdby,
            note=note,
            faculty_coordinator=self
        )

        note.save()
        return note
    
    @property
    def ce_url(self):
        return reverse_lazy('cis:faculty_coordinator', kwargs={
            'record_id': self.id})

    @staticmethod
    def import_from_csv(dictReader):
        """Import faculty coordinators from a csv.DictReader. Returns
        {status, records, summary}. See cis/services/importers/."""
        from cis.services.importers import FacultyImporter
        return FacultyImporter().process_csv(dictReader)

    @staticmethod
    def delete_record(record):
        """Delete a FacultyCoordinator and the rows it owns.

        The only two models pointing at FacultyCoordinator are PROTECT:
        FacultyCourseCoordinator.faculty_coordinator and
        FacultyCoordinatorNote.faculty_coordinator. Both are cleared first,
        inside the same transaction.atomic() as the record delete, so a
        failure partway through cannot destroy the coordinator's course
        assignments or notes while leaving the record behind -- either
        everything succeeds together, or none of it is kept.

        The account is never deleted here. CustomUser is protected by many
        foreign keys, so user.delete() raises ProtectedError for most real
        accounts; swallowing that is the bug this whole body of work exists
        to remove. Revoking the group is a separate explicit step --
        cis.services.role_access.revoke_access.
        """
        from django.db import transaction

        with transaction.atomic():
            FacultyCourseCoordinator.objects.filter(
                faculty_coordinator=record
            ).delete()

            FacultyCoordinatorNote.objects.filter(
                faculty_coordinator=record
            ).delete()

            record.delete()

        return True

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "fac_coordinatos.csv"
        fields = {
            "user.first_name": "First Name",
            "user.last_name": "Last Name",
            "user.address1": "Address1",
            "user.address2": "Address2",
            "user.city": 'City',
            'user.state': 'State',
            'user.postal_code': 'ZipCode',
            'user.primary_phone': 'PrimaryPhone',
            'user.email': "Email",
            'status': 'Status',
            'temp_id': 'TempID',
            'fac_assistant': 'Fac. Assistant'
        }

        return export_to_excel(file_name, records, fields)

class FacultyCourseCoordinator(models.Model):
    """
    Model to associate faculty with their courses
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    faculty_coordinator = models.ForeignKey('cis.FacultyCoordinator', on_delete=models.PROTECT)
    course = models.ForeignKey('cis.Course', on_delete=models.PROTECT)

    STATUS_OPTIONS = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS)

    class Meta:
        unique_together = (('faculty_coordinator', 'course'))


class FacultyTeacherAssignment(models.Model):
    """Which instructors a faculty member is responsible for, per course and year.

    A faculty member's instructor list is otherwise derived: every teacher
    holding a TeacherCourseCertificate for any course they administer. That has
    no notion of a year and no way for CE to say "these three instructors, not
    all eleven".

    The grain is (user, course, teacher, academic_year) on purpose -- a teacher
    who appears on two of the faculty's courses is assignable under each, and
    the fallback stays per-course. Absence of rows for (user, course, year) is
    itself the signal: that course falls back to the full certificate list, so
    a half-finished configuration over-shows rather than silently hiding
    instructors. Unassigning is deleting the row; there is deliberately no
    `status` field, because "rows exist, none active" and "no rows" would then
    mean opposite things.

    Keyed on CustomUser rather than FacultyCoordinator, whose own docstring
    says it is not used any more.

    All the FKs CASCADE: this is configuration, not a record of record, and a
    stale assignment row must never be the thing that blocks deleting a course
    or a teacher. `created_by` is bookkeeping and survives as NULL.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        'cis.CustomUser',
        on_delete=models.CASCADE,
        related_name='faculty_teacher_assignments',
    )
    course = models.ForeignKey(
        'cis.Course',
        on_delete=models.CASCADE,
        related_name='faculty_teacher_assignments',
    )
    teacher = models.ForeignKey(
        'cis.Teacher',
        on_delete=models.CASCADE,
        related_name='faculty_assignments',
    )
    academic_year = models.ForeignKey(
        'cis.AcademicYear',
        on_delete=models.CASCADE,
        related_name='faculty_teacher_assignments',
    )

    created_on = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'cis.CustomUser',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='faculty_teacher_assignments_created',
    )

    class Meta:
        unique_together = (('user', 'course', 'teacher', 'academic_year'),)
        indexes = [
            models.Index(
                fields=['user', 'course', 'academic_year'],
                name='cis_fta_user_course_year_idx',
            ),
        ]

    def __str__(self):
        return f'{self.user} / {self.course} / {self.teacher} ({self.academic_year})'
