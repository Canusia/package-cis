"""
Course types and the course types a high school is approved to offer.

CourseType is the tenant's classification of a section (Face-to-Face,
Online, HyFlex, ...); the SIS importer sets ClassSection.course_type by
`code`. HighSchoolCourseType records which types a school is approved for,
optionally at one campus only (blank campus = every campus).
"""
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from simple_history.models import HistoricalRecords

STATUS_OPTIONS = (
    ('Active', 'Active'),
    ('Inactive', 'Inactive'),
)


class CourseType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Stable value the importer classifies into; never relabel it, change `name`.
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # False = classify-only (e.g. developmental): never offered for approval.
    approvable = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default='Active')

    history = HistoricalRecords()

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class HighSchoolCourseType(models.Model):
    """A high school's approval to offer a course type."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    highschool = models.ForeignKey(
        'cis.HighSchool', on_delete=models.CASCADE, related_name='course_type_links')
    course_type = models.ForeignKey(
        'cis.CourseType', on_delete=models.PROTECT, related_name='highschool_links')
    # Blank = approved at every campus.
    campus = models.ForeignKey(
        'cis.Campus', on_delete=models.PROTECT, null=True, blank=True,
        related_name='highschool_course_type_links')
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default='Active')

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'high school course type'
        constraints = [
            # Two constraints because NULL never equals NULL in a unique index.
            models.UniqueConstraint(
                fields=['highschool', 'course_type', 'campus'],
                condition=Q(campus__isnull=False),
                name='hs_course_type_campus_once'),
            models.UniqueConstraint(
                fields=['highschool', 'course_type'],
                condition=Q(campus__isnull=True),
                name='hs_course_type_all_campuses_once'),
        ]

    def __str__(self):
        where = self.campus.name if self.campus_id else 'all campuses'
        return f'{self.highschool}: {self.course_type} ({where})'

    def clean(self):
        """An all-campus approval and a campus approval of the same type overlap."""
        if not (self.highschool_id and self.course_type_id):
            return
        others = HighSchoolCourseType.objects.filter(
            highschool_id=self.highschool_id, course_type_id=self.course_type_id,
        ).exclude(pk=self.pk)
        if self.campus_id:
            overlap = others.filter(campus__isnull=True).exists()
        else:
            overlap = others.filter(campus__isnull=False).exists()
        if overlap:
            raise ValidationError(
                'This school already has an approval for this course type that '
                'overlaps: use either one all-campus approval or per-campus approvals.')
