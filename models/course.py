# users/models.py
import uuid
from django.db import models
from django.dispatch import receiver
from django.db.models import JSONField

from multiselectfield import MultiSelectField
from cis.storage_backend import PrivateMediaStorage

from myce.models import MyCEBaseModel

from cis.utils import (
    export_to_excel,
    YES_NO_SELECT_OPTIONS,
    course_files_upload_path
)

from cis.models.teacher import TeacherCourseCertificate
from cis.models.customuser import CustomUser

class Category(models.Model):
    """
    Category model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500, unique=True)

    temp_id = models.SmallIntegerField(blank=True, null=True)

    def __str__(self):
        return self.name


class TechCenter(models.Model):
    """
    Tech Center model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500, unique=True)
    serving_area = models.CharField(max_length=1000, default=13210)

    def __str__(self):
        return self.name

    class Meta:
        unique_together = ['name']

    @classmethod
    def get_or_add(cls, name, serving_area):
        try:
            record = TechCenter.objects.get(
                name__iexact=name
            )
            return record
        except TechCenter.DoesNotExist:
            record = TechCenter(name=name, serving_area=serving_area)
            record.save()
            return record

class Location(models.Model):
    """
    Location model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        unique_together = ['name']
        ordering = ['name']
        
    @classmethod
    def get_or_add(cls, name):
        try:
            record = Location.objects.get(
                name__iexact=name
            )
            return record
        except Location.DoesNotExist:
            record = Location(name=name)
            record.save()
            return record

class Campus(models.Model):
    """
    Campus model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500, unique=True)
    code = models.CharField(max_length=500, unique=True)

    locations = models.ManyToManyField('cis.Location', blank=True)

    def __str__(self):
        return self.name

    class Meta:
        unique_together = ['name', 'code']

    @classmethod
    def get_or_add(cls, campus_code):
        try:
            record = Campus.objects.get(
                code=campus_code
            )
        except Campus.DoesNotExist:
            record = Campus(
                name=campus_code,
                code=campus_code
            )
            record.save()

        return record

    @classmethod
    def get_all(cls, prefix='UMS'):
        return Campus.objects.all()
    # filter(
    #         code__contains=prefix).all()

class College(models.Model):
    """
    College model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500, unique=True)
    campus = models.ForeignKey('cis.Campus', blank=True, on_delete=models.PROTECT, null=True)

    temp_id = models.SmallIntegerField(blank=True, null=True)
    def __str__(self):
        return self.name

class Department(models.Model):
    """
    Department model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500, unique=True)
    college = models.ForeignKey('cis.College', on_delete=models.PROTECT)
    
    temp_id = models.SmallIntegerField(blank=True, null=True)
    def __str__(self):
        return self.name

    class Meta:
        unique_together = (('name', 'college'))

class Cohort(MyCEBaseModel):
    """
    Cohort/Subject/Program model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=500)
    designator = models.CharField(max_length=10)
    department = models.ForeignKey('cis.Department', on_delete=models.PROTECT, null=True, blank=True)

    STATUS_OPTIONS = (
        ('', '---'),
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS, default='Active')

    temp_id = models.IntegerField(blank=True, null=True)
    def __str__(self):
        return self.name

    class Meta:
        unique_together = ['name', 'designator']

    @staticmethod
    def get_instructor_certificates(cohort_ids, return_type="queryset"):
        """
        get_instructor_certificates([cohort_ids], return_type="queryset")

        Returns a queryset of 'TeacherCourseCertificate' who have been 
        certified for 'course'
        """
        records = TeacherCourseCertificate.objects.filter(
            course__cohort__in=cohort_ids)
        if return_type == "queryset":
            return records

    @staticmethod
    def import_from_csv(dictReader):
        """Import Cohorts from CSV using the CohortImporter service."""
        from cis.services.importers import CohortImporter

        importer = CohortImporter()
        return importer.process_csv(dictReader)

    @classmethod
    def get_or_add(cls, cohort_designator, title):
        try:
            record = Cohort.objects.get(
                designator=cohort_designator
            )
        except Cohort.DoesNotExist:
            record = Cohort(
                name=title,
                designator=cohort_designator
            )
            record.save()
        return record

class Course(MyCEBaseModel):
    """
    Course model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    catalog_number = models.CharField(max_length=10)
    title = models.CharField(max_length=100)
    name = models.CharField(max_length=20, blank=True, null=True)
    
    campus = models.ForeignKey(
        'cis.Campus',
        on_delete=models.PROTECT, blank=True, null=True)

    department = models.ForeignKey(
        'cis.Department',
        on_delete=models.PROTECT, blank=True, null=True)
    cohort = models.ForeignKey('cis.Cohort', on_delete=models.PROTECT)
    credit_hours = models.FloatField(default=1)

    category = models.ForeignKey('cis.Category', on_delete=models.PROTECT, blank=True, null=True)

    STATUS_OPTIONS = [
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS, default='Active')

    note = models.TextField(
        blank=True,
        null=True
    )
    
    excerpt = models.TextField(
        blank=True,
        null=True
    )
    
    teacher_requirement = models.TextField(
        blank=True,
        null=True
    )
    
    description = models.TextField(
        blank=True,
        null=True
    )
    
    prereq = models.TextField(
        verbose_name='Pre-reqs',
        blank=True,
        null=True
    )

    STREAM_OPTIONS = (
        ('Humanities', 'Humanities & Social Sciences'),
        ('Languages', 'Languages'),
        ('STEM', 'STEM'),
        ('Business & Tech.', 'Business & Tech.'),
    )
    stream = MultiSelectField(
        max_length=100,
        choices=STREAM_OPTIONS,
        blank=True
    )
    
    FRESHMAN = 'FR'
    SOPHOMORE = 'SO'
    JUNIOR = 'JR'
    SENIOR = 'SR'

    GRADE_LEVEL = [
        (SENIOR, 'Senior - 12th grade'),
        (f"{SENIOR}*", 'Senior - 12th grade with recommendation'),
        (JUNIOR, 'Junior- 11th grade'),
        (f"{JUNIOR}*", 'Junior- 11th grade with recommendation'),
        (SOPHOMORE, 'Sophomore - 10th grade'),
        (f"{SOPHOMORE}*", 'Sophomore - 10th grade with recommendation'),
        (FRESHMAN, 'Freshman - 9th grade'),
        (f"{FRESHMAN}*", 'Freshman - 9th grade with recommendation'),
    ]

    registration_eligibility = MultiSelectField(
        max_length=100,
        choices=GRADE_LEVEL,
        default=['SR', 'JR']
    )

    url = models.URLField(max_length=200, blank=True, null=True)
    meta = JSONField(
        blank=True,
        null=True
    )

    temp_id = models.IntegerField(blank=True, null=True)

    # Look through access db to see other fields

    class Meta:
        unique_together = (("cohort", "catalog_number", 'campus'))
        ordering = ['cohort__designator', 'catalog_number']
    
    @property
    def uploads(self):
        from cis.models.course import CourseUpload

        return CourseUpload.objects.filter(
            course=self
        )

    @property
    def syllabi_uploads(self):
        from cis.models.course import CourseUpload

        return CourseUpload.objects.filter(
            course=self,
            media_type='Syllabus Template'
        )

    @property
    def shared_resource_uploads(self):
        from cis.models.course import CourseUpload

        return CourseUpload.objects.filter(
            course=self,
            media_type__in=['Course Resource', 'Shared Resource']
        )

    def __str__(self):
        return f"{self.name}"

    def sexy_description(self):
        result = "PreReq(s): "

        if self.prereq:
            result += self.prereq
        else:
            result += "None"

        result += "<br><br>"
        result += "Description: " + ( self.description if self.description else 'Not Available' )

        result += "<br><br>" + str(self.registration_eligibility)
        return result

    @property
    def areas_of_interest(self):
        return []

    @property
    def registration_eligibility_sexy(self):
        elig = ", ".join([f"{dict(self.GRADE_LEVEL)[level]}" for level in self.registration_eligibility])

        elig = elig.replace('9th grade with recommendation', '9th grade meets additional eligibility requirements and school recommendation')

        return elig

    @classmethod
    def available_for_new_schools(cls):
        streams = cls.STREAM_OPTIONS

        available_courses = []
        for stream, name in streams:
            courses = Course.objects.filter(
                stream__contains=stream,
                meta__available_for_new_schools='1'
            )

            for course in courses:
                a_course = {
                    'name': str(course),
                    'stream': stream,
                    'excerpt': course.excerpt,
                    'id': str(course.id),
                    'title': course.title,
                    'credit_hours': course.credit_hours,
                    'url': course.url
                }

                available_courses.append(a_course)
        return available_courses

    def add_note(self, createdby, note, **kwargs):
        from cis.models.note import CourseNote

        note = CourseNote(
            createdby=createdby,
            note=note,
            course=self
        )

        note.save()
        return note
    
    @staticmethod
    def import_from_csv(dictReader):
        """Import Courses from CSV using the CourseImporter service."""
        from cis.services.importers import CourseImporter

        importer = CourseImporter()
        return importer.process_csv(dictReader)

    @classmethod
    def add_or_update(cls, name, **kwargs):
        try:
            record = Course.objects.get(
                name=name
            )
        except Course.DoesNotExist:
            record = Course(
                name=name
            )

        try:
            # Add extra fields if present
            for key, value in kwargs.items():
                setattr(record, key, value)
        except Exception as e:
            print(e)
            pass
                
        record.save()
        return record


    @classmethod
    def get_or_add(cls, cohort, catalog_number, credit_hours=1, title='Update', name='', **kwargs):
        try:
            record = Course.objects.get(
                cohort=cohort,
                catalog_number=catalog_number
            )
        except Course.DoesNotExist:
            if credit_hours == '':
                credit_hours = 99
            
            record = Course(
                catalog_number=catalog_number,
                cohort=cohort,
                credit_hours=credit_hours,
                title=title,
                name=name
            )
            try:
                # Add extra fields if present
                for key, value in kwargs.items():
                    setattr(record, key, value)
            except:
                pass

            record.save()
        return record

    @staticmethod
    def get_instructors_for_course(course, return_type="queryset"):
        """
        Returns a queryset or Exports  'TeacherCourseCertificate' who have been 
        certified for 'course'
        """
        records = TeacherCourseCertificate.objects.filter(course=course)
        if return_type == "queryset":
            return records

        if return_type == "excel":
            file_name = "course_instructors.csv"
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
                "status": "Stage",
                "teacher_highschool.since": "Since",
                "teacher_highschool.highschool.name": "High School"
            }

            return export_to_excel(file_name, records, fields)

    @staticmethod
    def export_to_excel(records):
        """
        Write records to an Excel file
        """
        file_name = "courses.csv"
        fields = {
            'cohort.designator': "Course",
            "catalog_number": "Catalog Number",
            "title": "Title",
            "department.name": "Department",
            "cohort.name": "Cohort",
            "credit_hours": 'Credit Hours',
            'temp_id': 'TempID',
            'epp': 'EPP',
            'status': 'Status',
            'temp_id': 'TempID'
        }

        return export_to_excel(file_name, records, fields)

    @staticmethod
    def export_instructor_course_stages_to_excel(records):
        """
        Exports instructor course stages to an Excel file
        """
        file_name = "instructor-course-stages.csv"

        courses = records.values_list('id', flat=True)
        records = TeacherCourseCertificate.objects.filter(
            course__id__in=courses)

        fields = {
            'certificate_id': 'ID',
            'course.cohort.designator': "Course",
            "course.catalog_number": "Catalog Number",
            "course.title": "Title",
            "course.department.name": "Department",
            "course.cohort.name": "Cohort",
            "course.credit_hours": 'Credit Hours',
            "teacher_highschool.teacher.user.first_name": "First Name",
            "teacher_highschool.teacher.user.last_name": "Last Name",
            "teacher_highschool.teacher.user.email": 'Email',
            "status": "Stage",
            "since": "Since",
            "teacher_highschool.highschool.name": "High School"
        }

        return export_to_excel(file_name, records, fields)

    def get_faculty_coordinators(self, reviewer_roles=['Faculty'], return_type="queryset"):
        """
        Returns a queryset or Exports active 'CourseAdministrator'
        """
        if not reviewer_roles:
            reviewer_roles = ['Faculty']

        return CourseAdministrator.objects.get_ordered_by_role(
            role__in=reviewer_roles,
            status__iexact='active',
            course=self
        )

    @classmethod
    def get_administrators(self, course_ids=[], return_type="queryset"):
        """
        Returns a queryset or Exports active 'CourseAdministrator'
        """
        return CourseAdministrator.objects.filter(
            role__iexact='administrator',
            status__iexact='active',
            course__id__in=course_ids
        )


class CourseUpload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    course = models.ForeignKey('cis.Course', on_delete=models.PROTECT)

    MEDIA_TYPE = (
        ('Syllabus', 'Syllabus'),
        ('Syllabus Template', 'Syllabus Template'),
        ('Course Resource', 'Course Resource'),
    )
    media_type = models.CharField(
        max_length=30,
        choices=MEDIA_TYPE,
        default='Transcript'
    )

    description = models.TextField(blank=True)
    media = models.FileField(
        storage=PrivateMediaStorage(),
        upload_to=course_files_upload_path
    )

    uploaded_on = models.DateTimeField(auto_now=True)

    @property
    def file_name(self):
        import os
        return os.path.basename(self.media.name)

@receiver(models.signals.post_delete, sender=CourseUpload)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    if instance.media:
        instance.media.delete(save=False)
        return True
    return False

class CourseAppRequirement(models.Model):
    """
    Campus model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        'cis.Course',
        on_delete=models.CASCADE,
        blank=True,
        null=True
    )
    name = models.CharField(max_length=500)
    description = models.TextField(
        blank=True
    )

    STATUS_OPTIONS = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS, default='Active')

    required = models.CharField(
        max_length=10,
        choices=YES_NO_SELECT_OPTIONS,
        default=1
    )

    class Meta:
        unique_together = [
            ('course', 'name')
        ]

from django.db.models import Case, When, IntegerField
class CourseAdministratorManager(models.Manager):
    def get_ordered_by_role(self, **kwargs):
        # Apply any filters passed as kwargs
        queryset = self.filter(**kwargs)
        
        return queryset.annotate(
            role_order=Case(
                When(role='Administrator', then=1),
                When(role='Faculty', then=2),
                When(role='Dept. Chair', then=3),
                When(role='Dean', then=4),
                default=99,
                output_field=IntegerField(),
            )
        ).order_by('role_order')
    
class CourseAdministrator(models.Model):
    """
    Campus model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        'cis.Course',
        on_delete=models.CASCADE,
        blank=True,
        null=True
    )
    user = models.ForeignKey(
        'cis.CustomUser',
        on_delete=models.PROTECT
    )

    ROLE_OPTIONS = [
        ('Administrator', 'Administrator'),
        ('Faculty', 'Faculty'),
        ('FC Reviewer', 'FC Reviewer'),
        ('Visitor', 'Visitor'),
        ('Dept. Chair', 'Dept. Chair'),
        ('Dean', 'Dean'),
    ]
    role = models.CharField(
        max_length=20,
        choices=ROLE_OPTIONS,
        default='Administrator'
    )

    STATUS_OPTIONS = [
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS, default='Active')

    objects = CourseAdministratorManager()
    
    @property
    def faculty_id(self):
        try:
            return self.user.facultycoordinator.id
        except:
            return ''

    @classmethod
    def get_or_add(cls, course, user, role):
        try:
            record = CourseAdministrator.objects.get(
                course=course,
                user=user,
                role=role
            )
        except CourseAdministrator.DoesNotExist:
            record = CourseAdministrator(
                course=course,
                user=user,
                role=role
            )
            record.save()
        return record

class Section(models.Model):
    """
    Class Section model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section_number = models.CharField(max_length=10)
    class_number = models.CharField(max_length=10)

    start_date = models.DateField()
    end_date = models.DateField()

    term = models.ForeignKey('cis.term', on_delete=models.PROTECT)
    course = models.ForeignKey('cis.course', on_delete=models.PROTECT)
    high_school = models.ForeignKey('cis.HighSchool', on_delete=models.PROTECT)
    instructor = models.ForeignKey('cis.Teacher', on_delete=models.PROTECT)



class CohortParticipant(models.Model):
    """
    Base user model
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('cis.CustomUser', on_delete=models.PROTECT)

    suffix = models.CharField(max_length=10, blank=True, null=True)
    job_title = models.CharField(max_length=100, blank=True, null=True)

    status = models.CharField(max_length=10, blank=True, null=True)
    status_date = models.DateField(blank=True, null=True)
    
    avb_position = models.CharField(
        max_length=50, blank=True, null=True
    )
    avb_location = models.CharField(
        max_length=50, blank=True, null=True
    )
    avb_affiliation = models.CharField(
        max_length=50, blank=True, null=True
    )

    # Look through access db to see other fields
    def __str__(self):
        return self.user.first_name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        #if self._state.adding is True
        group = Group.objects.get(name='cohort_participant')
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

class CohortAffiliation(models.Model):
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False)

    cohort_participant = models.ForeignKey(
        'cis.CohortParticipant', on_delete=models.PROTECT)
    cohort = models.ForeignKey(
        'cis.Cohort', on_delete=models.PROTECT)
    
    STATUS_OPTIONS = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS)
    since = models.DateField(blank=True, null=True)

    class Meta:
        unique_together = (('cohort_participant', 'cohort'))
