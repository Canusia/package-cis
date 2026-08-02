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
