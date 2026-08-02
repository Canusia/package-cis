import uuid

from django.db import models

try:
    from django.db.models import JSONField
except ImportError:  # pragma: no cover
    from django.contrib.postgres.fields import JSONField


class BulkEnrollBatch(models.Model):
    """One bulk-enroll upload (a term + selected sections + a CSV of emails),
    awaiting (or past) preview/confirm."""

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('committed', 'Committed'),
        ('cancelled', 'Cancelled'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        'cis.CustomUser', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    source_filename = models.CharField(max_length=255, blank=True, default='')
    term = models.ForeignKey(
        'cis.Term', on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending')

    class Meta:
        ordering = ['-created_at']


class BulkEnrollRow(models.Model):
    """A single (email x selected-section) pairing and its validation outcome."""

    STATUS_CHOICES = (
        ('valid', 'Valid'),
        ('duplicate', 'Already enrolled (skipped)'),
        ('error', 'Error'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        BulkEnrollBatch, on_delete=models.CASCADE, related_name='rows')
    row_number = models.PositiveIntegerField()
    email = models.CharField(max_length=254, blank=True, default='')
    class_section = models.ForeignKey(
        'cis.ClassSection', on_delete=models.PROTECT, null=True, blank=True)
    section_label = models.CharField(max_length=255, blank=True, default='')
    student = models.ForeignKey(
        'cis.Student', on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='error')
    errors = JSONField(default=dict, blank=True)
    selected = models.BooleanField(default=False)
    result = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['row_number']
