"""
High School Model
"""
from email.policy import default
import os, uuid
from django.db import models
from django.contrib import messages, auth

from simple_history.models import HistoricalRecords

from multiselectfield import MultiSelectField

from cis.storage_backend import PrivateMediaStorage
from cis.models.teacher import (
    TeacherHighSchool, Teacher
)

from cis.utils import export_to_excel, hs_transcript_upload_path
from cis.models.section import ClassSection, StudentRegistration
from cis.models.term import Term
from cis.models.note import HighSchoolNote

def hs_type_choices():
    """Tenant-owned School Type vocabulary.

    Passed to the hs_type field as a *callable* on purpose: Django keeps the
    callable through deconstruct() and the migration writer serializes it as
    this function's import path, so migration files carry no tenant labels and
    relabeling generates no migration. cis/ is hand-copied between tenant
    repos, where per-tenant literals in migrations mean divergent histories.

    Resolution is lazy — MultiSelectField only consumes choices on first
    access because max_length is set explicitly — so this never runs at import
    time and cannot trip AppRegistryNotReady.
    """
    from cis.services.tenant_services import get_tenant_service
    return get_tenant_service('highschool_types').choices()


class HighSchoolTranscript(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    description = models.TextField(blank=True)
    media = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=hs_transcript_upload_path
    )

    highschool = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT)

    uploaded_on = models.DateTimeField(auto_now=True)
    uploaded_by = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)

    @property
    def file_name(self):
        return os.path.basename(self.media.name)
    
class HighSchoolCollegeAdvisor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    highschool = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT)
    advisor = models.ForeignKey('cis.CustomUser', on_delete=models.PROTECT)

    STATUS_OPTIONS = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default="Active")

    class Meta:
        unique_together = ['highschool', 'advisor']

class HighSchoolClassOffering(models.Model):
    """
    Non F2F class sections that are offered at the high school
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    highschool = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT)
    class_section = models.ForeignKey('cis.ClassSection', on_delete=models.PROTECT)

    room_alias = models.CharField(max_length=10, blank=True, null=True, default='')

    class Meta:
        unique_together = ['highschool', 'class_section']

    def __str__(self):
        return f"{self.class_section.course} @ {self.highschool.name}"

    def remove_offerings(self):

        if not self.has_students_from_highschool():
            self.delete()
            return True
        return False

    def has_students_from_highschool(self):
        """
        Returns True if class offering has students from the high school,
        False otherwise.

        Since registered students are only students in class if any student is present the function will return True
        """
        students_in_class = self.class_section.get_students()

        if not students_in_class:
            return False

        highschools = students_in_class.values_list(
            'student__highschool__id', flat=True
        )
        if self.highschool.id in highschools:
            return True
        return False

# add a model manager for high school
class HighSchoolManager(models.Manager):
    def active_highschools(self):
        return self.filter(status__iexact='active')

class HighSchool(models.Model):
    """
    High School model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500)

    history = HistoricalRecords()

    code = models.CharField(max_length=20, default='-')
    district = models.ForeignKey('cis.District', on_delete=models.PROTECT, blank=True, null=True)

    sau = models.CharField(max_length=100, default='-', blank=True, null=True)
    
    address1 = models.CharField(max_length=500, blank=True)
    address2 = models.CharField(max_length=500, blank=True)
    po_box = models.CharField(max_length=500, blank=True)

    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=100, blank=True)

    # Geocoding fields for map display
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    primary_phone = models.CharField(max_length=50, blank=True)
    secondary_phone = models.CharField(max_length=50, blank=True)
    fax = models.CharField(max_length=50, blank=True)

    url = models.URLField(max_length=200, blank=True, null=True)

    temp_id = models.IntegerField(blank=True, null=True)
    
    STATUS_OPTIONS = (
        ('', '---'),
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default="Active")
    state_code = models.CharField(max_length=10, blank=True)

    hs_type = MultiSelectField(
        max_length=150,
        choices=hs_type_choices,
        blank=True
    )

    @property
    def hs_type_labels(self):
        """Display labels for the stored School Type codes.

        Anything rendering hs_type to a user must go through this — the raw
        field holds codes ('zone_a'), not wording.
        """
        from cis.services.tenant_services import get_tenant_service
        return get_tenant_service('highschool_types').labels(self.hs_type)

    @property
    def hs_type_display(self):
        """Comma-joined hs_type_labels, for table cells and templates."""
        return ', '.join(self.hs_type_labels)

    PAY_TYPE_OPTIONS = (
        ('', ''),
        ('Student Pay', 'Student Pay'),
        ('School Full Pay', 'School Full Pay'),
        ('School Partial Pay', 'School Partial Pay'),
    )
    hs_pay_type = models.CharField(
        max_length=150,
        choices=PAY_TYPE_OPTIONS,
        blank=True,
        verbose_name='High School Pay Type',
        default='Student Pay'
    )

    access_approver = models.ForeignKey(
        'HSAdministrator',
        on_delete=models.PROTECT,
        blank=True,
        null=True
    )

    oncampus_sections = models.CharField(max_length=100, blank=True, null=True)

    objects = HighSchoolManager()
    
    class Meta:
        ordering = ['name']
        unique_together = ['name','code']

    def __str__(self):
        return self.name

    @property
    def advisor(self):
        return None
    
    def add_note(self, createdby, note, **kwargs):
        note = HighSchoolNote(
            createdby=createdby,
            note=note,
            highschool=self
        )

        note.save()
        return note

    def geocode_address(self):
        """Use Google Geocoding API to get lat/lng from address."""
        import requests
        from django.conf import settings

        if not self.address1 or not self.city:
            return False

        address = f"{self.address1}, {self.city}, {self.state} {self.postal_code}"
        api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', None)

        if not api_key:
            return False

        try:
            response = requests.get(
                'https://maps.googleapis.com/maps/api/geocode/json',
                params={
                    'address': address,
                    'key': api_key
                },
                timeout=10
            )
            data = response.json()

            if data.get('status') == 'OK' and data.get('results'):
                location = data['results'][0]['geometry']['location']
                self.latitude = location['lat']
                self.longitude = location['lng']
                return True
        except Exception:
            pass

        return False

    @classmethod
    def notify_new_counselor(cls, name, email):

        from django.template import Context, Template
        from django.contrib.auth.models import Group
        from django.template.loader import get_template
        from django.conf import settings

        from mailer import send_mail, send_html_mail
        
        from cis.settings.registration_email import registration_email
        
        email_settings = registration_email.from_db()

        email_template = Template(email_settings.get('new_counselor_email', 'change me'))
        subject = email_settings.get('new_counselor_email_subject', 'change me')

        context = Context({
            'name': name,
        })
        text_body = email_template.render(context)
        to = [email]

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
    
    @classmethod
    def get_or_add(cls, name, **kwargs):
        try:
            record = HighSchool.objects.get(
                name__iexact=name
            )
        except HighSchool.DoesNotExist:
            record = HighSchool(
                name=name
            )

            for key, value in kwargs.items():
                setattr(record, key, value)
            record.save()
        return record

    def administrators_in_highschool(self, status=['Active'], return_type='hsadministrator'):
        '''
        Returns a queryset of HSAdministrator in the high school.
        '''
        from cis.models.highschool_administrator import (
            HSAdministrator, HSAdministratorPosition
        )

        if status == 'can_manage_student_recommendation':
            admin_positions = HSAdministratorPosition.objects.filter(
                highschool=self.id,
                status__iexact='active',
                meta__manage_student_recommendation__iexact='yes'
            )
        else:
            admin_positions = HSAdministratorPosition.objects.filter(
                highschool=self.id,
                status__in=status
            )

        if return_type == 'hsadministratorposition':
            return admin_positions

        if not admin_positions:
            return HSAdministrator.objects.none()
        return HSAdministrator.objects.filter(
            id__in=admin_positions.values_list('hsadmin__id', flat=True)
        )

    def teachers_in_highschool(self, status=['In the Program'], return_type='teacher'):
        '''
        Returns a queryset of teachers in the high school. If the status is empty
        all teachers in the 'In the Program' status will be returned

        return_type = ['teacher', 'teacherhighschool']
        '''
        ht = TeacherHighSchool.objects.filter(
            highschool=self.id,
            status__in=status
        )

        if return_type == 'teacherhighschool':
            return ht

        ht = ht.values_list('teacher', flat=True)
        return Teacher.objects.filter(
            pk__in=set(ht)
        ).order_by('user__first_name')

    def on_campus_class_sections_available(self, terms):
        """
        Returns a queryset of ClassSection based on section # marked as
        available for high school. An empty ClassSection queryset is returned 
        if no section numbers have been set.

        terms => queryset of type Term
        """
        try:
            section_numbers = [int(section_number) for section_number in self.oncampus_sections.split(',')]
        except AttributeError as e:
            return ClassSection.objects.none()

        if len(section_numbers) == 0:
            return ClassSection.objects.none()

        class_sections = ClassSection.objects.filter(
            term__in=terms,
            section_number__number__in=section_numbers
        )

        print(class_sections)
        return class_sections

    @staticmethod
    def import_from_csv(dictReader, use_bulk=True):
        """
        Import high schools from CSV with optional bulk operations.

        Args:
            dictReader: CSV DictReader object
            use_bulk: If True, use bulk operations for better performance (default: True)

        Returns:
            Dict with 'status', 'records', and 'summary' keys
        """
        from cis.services.importers import HighSchoolImporter

        importer = HighSchoolImporter(
            use_bulk_operations=use_bulk,
            batch_size=500,
            use_transactions='none'
        )
        return importer.process_csv(dictReader)

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "highschools.csv"
        fields = {
            "name": "Name",
            "address1": "Address1",
            "address2": "Address2",
            "city": 'City',
            'state': 'State',
            'postal_code': 'ZipCode',
            'primary_phone': 'PrimaryPhone',
            'fax': 'Fax',
            'district.name': 'District',
            'status': 'Status',
            'state_code': 'State Code'
        }

        return export_to_excel(file_name, records, fields)

    def get_offered_classes(self, terms=None, includeStudentRegistered=False):
        """
        terms -> Term Queryset
        includeStudentRegistered -> This will bring in sections that student is in but
        may not be marked as offically offered in the high school


        Returns a queryset of ClassSection that are
        - offered in the high school
        - on-campus classes that are marked as 'being offered' in the high school

        If no terms are passed then class sections for all terms is returned
        """

        if not terms:
            terms = Term.objects.all()

        return ClassSection.objects.filter(
            highschool=self,
            term__in=terms
        )
