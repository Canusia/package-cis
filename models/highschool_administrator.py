# users/models.py
import uuid

from django.conf import settings
from django.urls import reverse_lazy
from django.db import models, IntegrityError
from django.contrib.auth.models import Group

from mailer import send_mail, send_html_mail

from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.template import Context, Template
from django.template.loader import get_template, render_to_string
from django.db.models import JSONField

from cis.utils import export_to_excel
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool

class HSAdministratorAccessRequest(models.Model):
    """
    Model to store access requests
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=100)
    email = models.EmailField(max_length=100)
    phone = models.CharField(max_length=20)

    highschool = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT)

    role = models.CharField(max_length=100)

    approver_name = models.CharField(max_length=100, blank=True, null=True)
    approver_email = models.EmailField(max_length=100, blank=True, null=True)
    approver_phone = models.CharField(max_length=20, blank=True, null=True)

    message = models.TextField(blank=True, null=True)

    submittedon = models.DateTimeField(auto_now_add=True)

    STATUS_OPTIONS = (
        ('Submitted', 'Submitted'),
        ('Approved', 'Approved'),
        ('Denied', 'Denied'),
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_OPTIONS,
        default='Submitted')

    @property
    def ce_url(self):
        return reverse_lazy('cis:hs_admin_access_request', kwargs={
            'record_id': self.id})

    def notify_on_submit(self):
        from cis.settings.access_request import access_request as access_request_settings

        config = access_request_settings.from_db()
        email = subject = ''

        subject = config.get('submitted_subject')
        email = config.get('submitted_email')

        email_template = Template(email)
        context = Context({
            'name': self.name,
            'highschool': self.highschool.name,
            'highschool_country': self.highschool.country
        })

        text_body = email_template.render(context)
        to = config.get('submitted_internal_notification', 'kadaji@gmail.com').split(',')

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )
        return True
        
    def send_email(self):
        from cis.settings.access_request import access_request as access_request_settings

        config = access_request_settings.from_db()
        email = subject = ''

        if self.status == 'Approved':
            email = config.get('approved_email', '2')
            subject = config.get('approved_subject', '2')
        elif self.status == 'Denied':
            email = config.get('denied_email', '22')
            subject = config.get('denied_subject', '22')
        else:
            return None

        email_template = Template(email)
        context = Context({
            'name': self.name,
            'password_reset_link': self.get_password_reset_link(),
        })

        text_body = email_template.render(context)
        to = [self.email]

        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })

        if getattr(settings, 'DEBUG', True):
            to = ['kadaji@gmail.com']

        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to
        )
        return True

    def get_password_reset_link(self):
        try:
            if self.status == 'Approved':
                hs_admin = HSAdministrator.objects.get(
                    user__email__iexact=self.email.lower()
                )

                return hs_admin.user.get_password_reset_link()
        except:
            return '-'

    def grant_access(self, form_data):
        first_name = self.name.split(" ")[0]
        try:
            last_name = self.name.split(" ")[1]
        except:
            last_name = ' '

        hs_administrator = HSAdministrator.create_new(
            first_name,
            last_name,
            self.email.lower(),
            self.phone
        )

        if HSPosition.objects.filter(
            name__iexact=self.role).exists():
            position = HSPosition.objects.get(name__iexact=self.role)
        else:
            position = HSPosition()
            position.name = self.role

            position.save()

        hs_admin_position = HSAdministratorPosition()
        hs_admin_position.highschool = self.highschool
        hs_admin_position.position = position
        hs_admin_position.hsadmin = hs_administrator
        hs_admin_position.status = 'Active'
        
        hs_admin_position.meta = {}        
        hs_admin_position.meta['manage_student_recommendation'] = form_data.get('manage_student_recommendation')

        try:
            hs_admin_position.save()
            return True
        except IntegrityError:
            return False

class HSAdministrator(models.Model):
    """
    Base user model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)
    #Look through access db to see other fields

    def __str__(self):
        return f"{self.user.last_name} {self.user.first_name}"


    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        #if self._state.adding is True
        # group = Group.objects.get(name='highschool_admin')
        # self.user.groups.add(group)


    @staticmethod
    def delete_record(record):

        user = record.user
        record.delete()

        # try to remove base user account if this was the only role
        try:
            user.delete()
        except:
            pass

        return True

    @property
    def ce_url(self):
        return reverse_lazy('cis:hs_admin', kwargs={
            'record_id': self.id})

    def can_manage_student_student_recommendation(self, highschool_id):
        return HSAdministratorPosition.objects.filter(
            hsadmin=self,
            status__iexact='active',
            meta__manage_student_recommendation__iexact='yes',
            highschool__id=highschool_id
        ).exists()
    
    def get_highschools(self, status='Active'):
        """
        Return a HighSchool queryset for highschool_admin. If status is 
        not passed then only HighSchool objects with 'Active' roles 
        is returned
        """
        try:
            highschool_ids = HSAdministratorPosition.objects.filter(
                status=status,
                hsadmin__id=self.id).values_list('highschool', flat=True)

            return HighSchool.objects.filter(id__in=highschool_ids)
        except HSAdministratorPosition.DoesNotExist:
            return []

    def can_manage_student_recommendation(self, highschool_id):
        from cis.models.highschool_administrator import HSAdministratorPosition

        # A student with no high school yields highschool_id=None. The filter
        # below would return False for it anyway, but only by accident; make
        # the refusal explicit so a future filter change cannot turn a missing
        # high school into a match.
        if not highschool_id:
            return False

        return HSAdministratorPosition.objects.filter(
            highschool__id=highschool_id,
            status__iexact='active',
            meta__manage_student_recommendation__iexact='yes',
            hsadmin=self
        ).exists()

    def get_recommendation_highschools(self):
        """High schools where this admin may manage student recommendations.

        Queryset counterpart to can_manage_student_recommendation(), for
        filtering lists. The two must agree, so both key off the same active
        position plus the manage_student_recommendation meta flag. Callers that
        show pending-recommendation work should use this rather than
        get_highschools(), which is every school the admin holds any position
        at.
        """
        from cis.models.highschool_administrator import HSAdministratorPosition

        highschool_ids = HSAdministratorPosition.objects.filter(
            hsadmin__id=self.id,
            status__iexact='active',
            meta__manage_student_recommendation__iexact='yes',
        ).values_list('highschool', flat=True)

        return HighSchool.objects.filter(id__in=highschool_ids)

    @classmethod
    def create_new(cls, first_name, last_name, email, primary_phone='', **kwargs):
        #create a CustomUser object
        user = CustomUser()
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.username = email.lower()
        user.primary_phone = primary_phone
        
         #check if user email is already in the system
        if not CustomUser.objects.filter(email=email).exists():
            user.save()
        else:
            user = CustomUser.objects.get(email=email)
            
        record = HSAdministrator(user=user)
        try:
            record.save()
        except IntegrityError:
            record = HSAdministrator.objects.get(
                user=user
            )
        return record

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "highschool_administrators.csv"
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

    @staticmethod
    def import_from_csv(dictReader):
        """Import HS Members from CSV using the HSMemberImporter service."""
        from cis.services.importers import HSMemberImporter

        importer = HSMemberImporter()
        return importer.process_csv(dictReader)

    @classmethod
    def get_or_add(cls, email, **kwargs):
        try:
            record = HSAdministrator.objects.get(
                user__email__iexact=email
            )
        except HSAdministrator.DoesNotExist:
            user = CustomUser.get_or_add(
                username=email,
                email=email,
                **kwargs
            )

            try:
                record = HSAdministrator(user=user)
                record.save()

                #highschool_admin role is added in the save method
            except:
                return None
        return record

class HSPosition(models.Model):
    """
    HS Positions models
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)

    YES_NO_OPTIONS = (
        ('no', 'No'),
        ('yes', 'Yes')
    )

    temp_id = models.IntegerField(blank=True, null=True)

    can_manage_class_offering = models.CharField(
        choices=YES_NO_OPTIONS,
        max_length=3,
        default='no'
    )

    def __str__(self):
        return self.name

    class Meta:
        unique_together = ['name']

    @classmethod
    def get_or_add(cls, name, **kwargs):
        try:
            record = HSPosition.objects.get(
                name__iexact=name
            )
        except HSPosition.DoesNotExist:
            record = HSPosition(
                name=name
            )
            record.save()
        return record

class HSAdministratorPosition(models.Model):
    """
    Model to associate hs admin with their position in high schools
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    hsadmin = models.ForeignKey('cis.HSAdministrator', on_delete=models.PROTECT)
    highschool = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT)
    position = models.ForeignKey('cis.HSPosition', on_delete=models.PROTECT)

    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)

    since = models.DateTimeField(blank=True, null=True)
    meta = JSONField(default=dict)

    STATUS_OPTIONS = [
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
        # ('Retired', 'Retired'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS)

    class Meta:
        unique_together = (('hsadmin', 'highschool', 'position'))


    def toggle_student_recommendation(self):
        if self.status == 'Active':
            if self.meta.get('manage_student_recommendation') == 'Yes':
                self.meta['manage_student_recommendation'] = 'No'
            else:
                self.meta['manage_student_recommendation'] = 'Yes'
        
        self.save()

    def toggle_status(self):
        if self.status == 'Active':
            self.status = 'Inactive'
        else:
            self.status = 'Active'
        
        self.save()

    @classmethod
    def get_or_add(cls, hsadmin, highschool, position, status):
        try:
            record = HSAdministratorPosition.objects.get(
                hsadmin=hsadmin,
                highschool=highschool,
                position=position
            )
        except HSAdministratorPosition.DoesNotExist:
            record = HSAdministratorPosition(
                hsadmin=hsadmin,
                highschool=highschool,
                position=position,
                status=status
            )
            record.save()
        return record
