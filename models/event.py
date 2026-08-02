# users/models.py
import uuid
import csv
from django.http import HttpResponse

from django.db import models
from django.contrib.auth.models import Group
from django.db.models import JSONField

from cis.utils import export_to_excel

class Event(models.Model):
    """
    Speaker model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    venue = models.ForeignKey("cis.Venue", on_delete=models.PROTECT)

    start_time = models.DateTimeField(verbose_name="Start Time")
    end_time = models.DateTimeField(verbose_name="End Time")

    EVENT_TYPES = (
        ('Type 1', 'Type 1`'),
        ('Type 2', 'Type 2'),
        ('Type 3', 'Type 3'),
    )
    type = models.CharField(max_length=30, choices=EVENT_TYPES, default="Type 1")

    term_tbd = models.ForeignKey("cis.Term", on_delete=models.PROTECT, related_name='term_tbd')

    created_on = models.DateTimeField(auto_now=True)
    created_by_tbd = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT, related_name='created_by_tbd')

    def get_item_info(self, type='Refreshment'):
        refreshment = EventItem.objects.filter(
            item_type=type,
            event=self
        )
        if not refreshment:
            return {
                'event':self.id,
                'id':-1,
                'ajax':1
                }

        item = refreshment[0].item
        item['event'] = self.id
        item['id'] = refreshment[0].id
        item['ajax'] = 1
        return item

class EventSpeaker(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey('cis.Event', on_delete=models.PROTECT)
    speaker = models.ForeignKey('cis.Speaker', on_delete=models.PROTECT)
    created_on = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)

    class Meta:
        unique_together = ['event', 'speaker']

class EventCohort(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey('cis.Event', on_delete=models.PROTECT)
    cohort = models.ForeignKey('cis.Cohort', on_delete=models.PROTECT)
    created_on = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)

    class Meta:
        unique_together = ['event', 'cohort']

class EventItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey('cis.Event', on_delete=models.PROTECT)

    item = JSONField()

    ITEM_OPTIONS = (
        ('speaker', 'Speaker'),
        ('refreshment', 'Refreshment'),
        ('copies', 'Copies'),
        ('cis expense', 'CIS Expense'),
        ('cohort expense', 'Cohort Expense'),
    )
    item_type = models.CharField(max_length=30, choices=ITEM_OPTIONS, default="speaker")

    @classmethod
    def save_item(cls, item_type, item_form):

        if item_form.cleaned_data['id'] == '-1':
            item = cls()
        else:
            item = cls.objects.get(pk=item_form.cleaned_data['id'])

        item.item_type = item_type
        item.event = Event.objects.get(pk=item_form.cleaned_data['event'])
        item.item = dict((k, str(v)) for k,v in item_form.cleaned_data.items())

        item.save()
        return item

class EventAttendee(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  

    event = models.ForeignKey('cis.Event', on_delete=models.PROTECT)
    user = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)

    STATUS_OPTIONS = (
        ('---', '---'),
        ('Invited', 'Invited'),
        ('Confirmed', 'Confirmed'),
        ('Attended', 'Attended'),
        ('Not Attended', 'Not Attended'),
    )
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default="---")

    PARTICIPATION_OPTIONS = (
        ('Optional', 'Optional'),
        ('Required', 'Required'),
    )
    participation = models.CharField(max_length=30, choices=PARTICIPATION_OPTIONS, default="Optional")

    class Meta:
        unique_together = ['event', 'user']

    @staticmethod
    def add_cohort_instructors_to_guest_list(event, cohort):
        """
        Adds all instructors in the cohort to the event's guest list. Returns the 
        number of instructors added to the guest list
        """
        from cis.models.course import Cohort
        instructor_certificates = Cohort.get_instructor_certificates([cohort.id])

        num_added = 0        
        for cert in instructor_certificates:
            try:
                attendee = EventAttendee()
                attendee.event = event
                attendee.attendee = cert.teacher_highschool.teacher.user

                attendee.save()
                num_added += 1
            except:
                #This should go here only for dup user record
                pass

        return num_added

class Speaker(models.Model):
    """
    Speaker model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)
    title = models.CharField(max_length=50, blank=True)

    #Look through access db to see other fields

    def __str__(self):
        return self.user.first_name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        #if self._state.adding is True
        group = Group.objects.get(name='speaker')
        self.user.groups.add(group)

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "speakers.csv"
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

class Venue(models.Model):
    """
    Venue model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500)

    address1 = models.CharField(max_length=500, blank=True)
    address2 = models.CharField(max_length=500, blank=True)

    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=100, blank=True)

    primary_phone = models.CharField(max_length=50, blank=True)
    emergency_phone = models.CharField(max_length=50, blank=True)
    emergency_contact = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.name

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "venues.csv"
        fields = {
            "name": "Name",
            "address1": "Address1",
            "address2": "Address2",
            "city": 'City',
            'state': 'State',
            'postal_code': 'ZipCode',
            'primary_phone': 'PrimaryPhone',
            'emergency_phone': 'Emergency Phone',
            'emergency_contact': 'Emergency Contact',
        }
        return export_to_excel(file_name, records, fields)
