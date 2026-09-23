# users/models.py
import uuid
from django.db import models
from django.dispatch import receiver
from django.db.models import JSONField
from django.db.models import Q

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

class DocumentType(models.Model):
    """The document vocabulary, owned by CE admins rather than by code.

    Replaces two competing lists: the hardcoded DOCUMENT_TYPES tuple in each
    tenant's course_document_types.py (what a course could require) and the
    free-text cis.settings.support_docs['types'] lines (what a student could
    upload). Those never agreed, and nothing could make them.

    `code` is stable and never edited; `label` is the only tenant-facing
    wording. That split is the property both previous designs lacked:
    relabeling 'TSI Assessment' to 'TSI Score' updates every screen and
    detaches nothing.

    Retire a type with status='Inactive', never by deleting it — both FKs
    pointing here are PROTECT.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    code = models.SlugField(max_length=100)
    label = models.CharField(max_length=255)

    STATUS_OPTIONS = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    status = models.CharField(
        max_length=10, choices=STATUS_OPTIONS, default='Active')

    # Nullable purely as a backward-compatibility affordance for rows that
    # predate campus assignment. NULL means *unassigned*, never "applies to
    # every campus" -- #47 makes it required once every tenant has backfilled.
    campus = models.ForeignKey(
        'cis.Campus', blank=True, null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            # Two partial constraints rather than unique_together('campus',
            # 'code'): Postgres treats NULLs as distinct in a unique index, so
            # the simple form would happily allow two legacy null-campus rows
            # with the same code. nulls_distinct=False would also work but
            # needs PostgreSQL 15+.
            models.UniqueConstraint(
                fields=['code'], condition=Q(campus__isnull=True),
                name='documenttype_unique_code_unassigned'),
            models.UniqueConstraint(
                fields=['campus', 'code'], condition=Q(campus__isnull=False),
                name='documenttype_unique_code_per_campus'),
        ]
        ordering = ['label']

    def __str__(self):
        return self.label

    @classmethod
    def normalize(cls, value, campus=None):
        """Resolve a code or a display label to a DocumentType, or None.

        Case-insensitive on both, so spreadsheets and settings lines that
        carry human labels keep working. Returns None rather than raising so
        callers decide whether an unmatched value is an error (the seeding
        command) or a silent skip.
        """
        if value is None:
            return None
        candidate = str(value).strip()
        if not candidate:
            return None

        rows = cls.objects.filter(campus=campus)
        folded = candidate.casefold()
        for row in rows:
            if folded in (row.code.casefold(), row.label.casefold()):
                return row
        return None


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
        # The reverse manager, not a fresh queryset: this is what lets
        # prefetch_related('courseupload_set') reach all three properties.
        # CourseSerializer declares all three, so a fresh queryset here cost
        # three queries per row on every feed that nests a course (#67).
        return self.courseupload_set.all()

    @property
    def syllabi_uploads(self):
        # Narrows the rows `uploads` already cached, in Python. A .filter()
        # on the manager would issue its own query and miss the prefetch.
        return [u for u in self.uploads
                if u.media_type == 'Syllabus Template']

    @property
    def shared_resource_uploads(self):
        return [u for u in self.uploads
                if u.media_type in ('Course Resource', 'Shared Resource')]

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

DEFAULT_DOCUMENT_TYPES = (
    ('transcript',  'High School Transcript'),
    ('tsi',         'TSI Assessment'),
    ('shot_record', 'Immunization Record'),
)


def course_document_choices():
    """Course Document vocabulary, tenant-overridable.

    Passed to the `document` field as a *callable* on purpose, the same way
    hs_type_choices() is: Django keeps the callable through deconstruct() and the
    migration writer serializes it as this function's import path, so migration
    files carry no tenant labels and relabeling the vocabulary generates no
    migration.

    Uses the *opt-in* seam (get_tenant_override) rather than the required-module
    form hs_type_choices uses. cis has a sensible default vocabulary here, and a
    required module would break the course pages of every tenant that adopts this
    version before shipping its own course_document_types.py. A tenant overrides
    by defining choices() in that module; one that does not is unaffected.

    Resolution is lazy — CharField only consumes choices when they are needed —
    so this never runs at import time and cannot trip AppRegistryNotReady.
    """
    from cis.services.tenant_services import get_tenant_override
    override = get_tenant_override('course_document_types', 'choices')
    if override is not None:
        return override()
    return list(DEFAULT_DOCUMENT_TYPES)


def student_grade_choices():
    """The four student grade levels, without Student.GRADE_LEVEL's blank sentinel.

    Reuses Student.GRADE_LEVEL rather than introducing a third grade vocabulary
    (cis.utils.STUDENT_GRADE_OPTIONS is the second, same codes with bare labels).
    The ('', 'Select') entry is a form placeholder and is meaningless for a
    MultiSelectField, so it is dropped. Course.GRADE_LEVEL is deliberately not
    reused: its starred 'with recommendation' codes express registration
    eligibility, not a grade.
    """
    from cis.models.student import Student
    return [(code, label) for code, label in Student.GRADE_LEVEL if code]


class CourseDocumentRequirement(models.Model):
    """A document a course requires of a student, optionally scoped to grades.

    Informational only: requirements inform the student and counsellor and never
    pre-block enrolment, so nothing may use this table to filter a course list.

    Distinct from CourseAppRequirement, which is the *instructor application*
    checklist (read through cis/models/teacher_applicant.py) and is free text.
    This one is a controlled vocabulary that downstream code branches on.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        'cis.Course',
        on_delete=models.CASCADE
    )

    document = models.CharField(max_length=100, choices=course_document_choices)

    # Blank means "all grades", so a requirement never silently applies to nobody
    # and the no-grade-dimension default matches existing behaviour.
    grade_levels = MultiSelectField(
        max_length=100,
        choices=student_grade_choices,
        blank=True
    )

    description = models.TextField(blank=True)

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
            ('course', 'document')
        ]

    def __str__(self):
        return f"{self.course} / {self.document}"

    @property
    def document_label(self):
        """Display label for the stored document code.

        Anything rendering `document` to a user must go through this — the column
        holds a code ('transcript'), not wording.
        """
        from cis.services.tenant_services import get_tenant_override
        override = get_tenant_override('course_document_types', 'label_for')
        if override is not None:
            return override(self.document)
        # Falls back to the code rather than raising: a code retired from the
        # vocabulary must not break pages showing requirements still carrying it.
        return dict(DEFAULT_DOCUMENT_TYPES).get(self.document, self.document)

    @property
    def grade_level_labels(self):
        """Display labels for the scoped grades, or ['All grades'] when unscoped."""
        if not self.grade_levels:
            return ['All grades']
        labels = dict(student_grade_choices())
        return [labels.get(code, code) for code in self.grade_levels]

    def applies_to_grade(self, grade):
        """True when `grade` is in scope.

        Empty grade_levels means every grade, which is why this is the single
        place that semantics lives rather than being re-derived per caller.
        """
        if not self.grade_levels:
            return True
        return grade in self.grade_levels


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
