import uuid

from django.db import models

try:
    from django.db.models import JSONField
except ImportError:  # pragma: no cover
    from django.contrib.postgres.fields import JSONField


class StudentImportBatch(models.Model):
    """One uploaded CSV awaiting (or past) preview/confirm."""

    SCOPE_CHOICES = (('ce', 'CE Admin'), ('highschool_admin', 'High School Admin'))
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
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='ce')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    class Meta:
        ordering = ['-created_at']


class StudentImportRow(models.Model):
    """A single parsed CSV row, with its validation outcome."""

    STATUS_CHOICES = (
        ('valid', 'Valid'),
        ('duplicate', 'Duplicate (skipped)'),
        ('error', 'Error'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        StudentImportBatch, on_delete=models.CASCADE, related_name='rows')
    row_number = models.PositiveIntegerField()
    raw_data = JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='error')
    errors = JSONField(default=dict, blank=True)
    selected = models.BooleanField(default=False)
    result = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['row_number']
