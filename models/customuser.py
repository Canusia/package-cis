# users/models.py
import logging
from django.contrib.auth.models import AbstractUser
from django.db import models

from django.core.validators import validate_email

from django.contrib.auth.models import Group
from django.contrib.sites.models import Site

from django.conf import settings

from django.db.models import JSONField
from model_utils import FieldTracker
from simple_history.models import HistoricalRecords
from cis.utils import export_to_excel

logger = logging.getLogger(__name__)

class CustomUser(AbstractUser):
    """
    Base user model
    """
    history = HistoricalRecords()

    middle_name = models.CharField(max_length=128, blank=True, null=True)
    suffix = models.CharField(max_length=128, blank=True, null=True)
    
    last_updated_on = models.DateTimeField(auto_now=True, blank=True, null=True)
    
    salutation = models.CharField(max_length=500, blank=True, null=True)
    ssn = models.CharField(max_length=15, blank=True, null=True)
    
    psid = models.CharField(max_length=20, blank=True, null=True)
    alt_email = models.EmailField(blank=True)

    alt_username = models.CharField(max_length=20, blank=True, null=True)
    
    secondary_email = models.EmailField(blank=True)
    email = models.EmailField(blank=False, unique=True, validators=[validate_email])

    address1 = models.CharField(max_length=500, blank=True)
    address2 = models.CharField(max_length=500, blank=True)
    po_box = models.CharField(max_length=500, blank=True)

    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    county = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=100, blank=True)

    primary_phone = models.CharField(max_length=50, blank=True)
    secondary_phone = models.CharField(max_length=50, blank=True)
    alt_phone = models.CharField(max_length=50, blank=True)

    date_of_birth = models.DateField(blank=True, null=True)
    country_of_birth = models.CharField(max_length=3, blank=True, null=True)

    account_enabled = models.BooleanField(default=False)
    require_password_reset = models.BooleanField(default=False)

    # PT-40: brute-force lockout on the email/password login.
    failed_login_attempts = models.PositiveIntegerField(default=0)
    account_locked = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, null=True)

    campus = JSONField(blank=True, null=True)
    education_background = JSONField(blank=True, null=True)
    previous_names = models.CharField(max_length=500, blank=True, null=True)
    
    tracker = FieldTracker(fields=['psid'])
    
    def __str__(self):
        return f"{self.last_name}, {self.first_name} "

    MAX_FAILED_LOGINS = 3

    def register_failed_login(self):
        """Count a failed email/password attempt; lock at MAX_FAILED_LOGINS."""
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        if self.failed_login_attempts >= self.MAX_FAILED_LOGINS:
            self.account_locked = True
        self.save(update_fields=['failed_login_attempts', 'account_locked'])

    def reset_failed_login(self):
        """Clear the failure counter after a successful login."""
        if self.failed_login_attempts or self.account_locked:
            self.failed_login_attempts = 0
            self.account_locked = False
            self.save(update_fields=['failed_login_attempts', 'account_locked'])

    def unlock(self):
        """Staff-initiated unlock: clear lock and counter."""
        self.failed_login_attempts = 0
        self.account_locked = False
        self.save(update_fields=['failed_login_attempts', 'account_locked'])

    @property
    def ssn_sexy(self):
        if not self.ssn:
            return ''
        return self.ssn
    
    class Meta:
        permissions = [
            ('create_user', 'Can create new user')
        ]
        ordering = ['last_name']

    @property
    def _date_of_birth(self):
        return self.date_of_birth.strftime('%m/%d/%Y')

    @classmethod
    def active_staff_at_campus(cls, campus_id):
        return cls.objects.filter(
            is_active=True,
            campus__process_campus__contains=str(campus_id)
        )

    def get_courses_overseeing(self):
        from cis.models.course import CourseAdministrator
        return CourseAdministrator.objects.filter(
            user=self
        ).values_list('course__id', flat=True)
    
    @classmethod
    def add_new_staff(cls, form):
        staff_group = Group.objects.get(name='ce')

        if CustomUser.objects.filter(username=form.cleaned_data['username']).exists():
            user = CustomUser.objects.get(username=form.cleaned_data['username'])
        else:
            user = CustomUser()

        data = form.cleaned_data

        user.first_name = form.cleaned_data['first_name']
        user.last_name = form.cleaned_data['last_name']
        user.email = form.cleaned_data['email']
        user.username = form.cleaned_data['username'].lower()
        user.is_staff = True
        user.is_active = True if form.cleaned_data['is_active'] == 'Yes' else False

        if not user.campus:
            user.campus = {}

        if data.get('password'):
            user.set_password(data.get('password'))

        user.campus['process_campus'] = form.cleaned_data['process_campus']
        user.campus['default_campus'] = form.cleaned_data['default_campus']

        user.campus['manage_settings'] = form.cleaned_data['manage_settings']
        user.campus['manage_staff_accounts'] = form.cleaned_data['manage_staff_accounts']

        user.save()
        user.groups.add(staff_group)
        return user

    def update(self, form):
        '''Updates user details or can I override the save method??'''

        data = form.cleaned_data
        
        self.first_name = form.cleaned_data['first_name']
        self.last_name = form.cleaned_data['last_name']
        self.email = form.cleaned_data['email']
        self.is_staff = True
        self.username = form.cleaned_data['username'].lower()
        self.is_active = True if form.cleaned_data['is_active'] == 'Yes' else False

        if not self.campus:
            self.campus = {}

        if data.get('password'):
            self.set_password(data.get('password'))

        self.campus['process_campus'] = form.cleaned_data['process_campus']
        self.campus['default_campus'] = form.cleaned_data['default_campus']
        self.campus['manage_settings'] = form.cleaned_data['manage_settings']
        self.campus['manage_staff_accounts'] = form.cleaned_data['manage_staff_accounts']

        self.save()

    @property
    def can_edit_users(self):
        if self.is_superuser:
            return True

        perms = self.campus
        if not perms:
            perms = {}

        return True if perms.get('manage_staff_accounts') == 'Yes' else False

    @property
    def can_edit_settings(self):
        if self.is_superuser:
            return True
        
        perms = self.campus
        if not perms:
            perms = {}
        return True if perms.get('manage_settings') == 'Yes' else False
       
    def get_roles(self):
        """
        Returns a list of roles the current user belongs to
        """
        return [g.name for g in self.groups.all()]

    def get_highschools_for_admin(self):
        from cis.models.highschool_administrator import (
            HSAdministrator, HSAdministratorPosition
        )

        hs_admin_accounts = HSAdministrator.objects.filter(
            user__id=self.id
        )

        highschools = HSAdministratorPosition.objects.filter(
            hsadmin__in=hs_admin_accounts
        ).distinct('highschool').values_list(
            'highschool', flat=True
        )

        return highschools

    @classmethod
    def get_or_add(cls, username, email, **kwargs):
        try:
            record = CustomUser.objects.get(
                username__iexact=username.lower()
            )
        except CustomUser.DoesNotExist:
            record = CustomUser()
            record.username = username
            record.email = email

        try:
            # Add extra fields if present
            for key, value in kwargs.items():
                setattr(record, key, value)
            record.save()
        except Exception as e:
            logger.error('Error while adding user ' + str(e))
            return CustomUser.objects.none()

        return record

    @property
    def password_reset_link(self):
        return self.get_password_reset_link()
    
    def send_password_reset_email(self):
        from cis.views.password_management import cisPasswordResetForm
        form = cisPasswordResetForm(request=None, data={'email': self.email})

        if not form.is_valid():
            return False
        form.save()
        return True
    
    def get_password_reset_link(self):
        from django.shortcuts import reverse
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator as token_generator

        current_site = Site.objects.get_current()
        domain = current_site.domain

        if not domain.startswith('https://'):
            domain = 'https://' + str(domain)
            
        passwd_reset = {
            'uid': urlsafe_base64_encode(force_bytes(self.pk)),
            'user': self,
            'token': token_generator.make_token(self)
        }

        password_reset_link = f'{domain}'+reverse('password_reset_confirm', kwargs={
            'uidb64':passwd_reset['uid'],
            'token':passwd_reset['token']
        })

        return password_reset_link


    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "users.csv"
        fields = {
            'first_name': "First Name",
            "last_name": "Last Name",
            "email": "Email",
            "created_at": "Created On",
        }

        return export_to_excel(file_name, records, fields)
