# users/models.py
import uuid
import csv
from django.http import HttpResponse

from django.db import models
from django.contrib.auth.models import Group

from cis.utils import export_to_excel

class District(models.Model):
    """
    District model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500)

    address1 = models.CharField(max_length=500, blank=True)
    address2 = models.CharField(max_length=500, blank=True)

    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=100, blank=True)

    primary_phone = models.CharField(max_length=50, blank=True)
    temp_id = models.IntegerField(blank=True, null=True)

    STATUS_OPTIONS = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

    @classmethod
    def get_or_add(cls, name):
        try:
            record = District.objects.get(
                name__iexact=name
            )
        except District.DoesNotExist:
            record = District(
                name=name
            )
            record.save()
        return record

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "districts.csv"
        fields = {
            "name": "Name",
            "address1": "Address1",
            "address2": "Address2",
            "city": 'City',
            'state': 'State',
            'postal_code': 'ZipCode',
            'primary_phone': 'PrimaryPhone',
            'status': 'Status',
            'temp_id': 'TempID'
        }
        return export_to_excel(file_name, records, fields)

class DistrictPosition(models.Model):
    """
    District Positions models
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)


    @classmethod
    def get_or_add(cls, name):
        try:
            record = DistrictPosition.objects.get(
                name__iexact=name
            )
        except DistrictPosition.DoesNotExist:
            record = DistrictPosition(
                name=name
            )
            record.save()
        return record
    
    def __str__(self):
        return self.name

class DistrictAdministrator(models.Model):
    """
    Base user model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)

    # Look through access db to see other fields
    def __str__(self):
        return self.user.first_name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        #if self._state.adding is True
        group = Group.objects.get(name='district_admin')
        self.user.groups.add(group)

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "district_administrators.csv"
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
            'temp_id': 'TempID'
        }

        return export_to_excel(file_name, records, fields)

class DistrictAdministratorPosition(models.Model):
    """
    Model to associate district admin with their position in high schools
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    district_admin = models.ForeignKey('cis.DistrictAdministrator', on_delete=models.PROTECT)
    district = models.ForeignKey('cis.District', on_delete=models.PROTECT)
    position = models.ForeignKey('cis.DistrictPosition', on_delete=models.PROTECT)

    STATUS_OPTIONS = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
        ('Retired', 'Retired'),
    )
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS)

    class Meta:
        unique_together = (('district_admin', 'district', 'position'))
