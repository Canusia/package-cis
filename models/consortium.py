"""
High school consortiums.

A consortium is a group of high schools whose students may take sections
hosted at each other's schools. Membership is explicit and may cross
districts; each member chooses how its own students are billed for a
section hosted at another member (billing_basis).
"""
import uuid

from django.db import models
from simple_history.models import HistoricalRecords

STATUS_OPTIONS = (
    ('Active', 'Active'),
    ('Inactive', 'Inactive'),
)


class Consortium(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default='Active')

    history = HistoricalRecords()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ConsortiumMembership(models.Model):
    """A high school's membership in a consortium."""
    BILLING_HOST_SCHOOL = 'host_school'
    BILLING_HOME_SCHOOL = 'home_school'
    BILLING_STUDENT_PAY = 'student_pay'
    BILLING_BASIS_OPTIONS = (
        (BILLING_HOST_SCHOOL, "Hosting school's pay type"),
        (BILLING_HOME_SCHOOL, "Student's home school's pay type"),
        (BILLING_STUDENT_PAY, 'Student pays'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    consortium = models.ForeignKey(
        'cis.Consortium', on_delete=models.CASCADE, related_name='memberships')
    highschool = models.ForeignKey(
        'cis.HighSchool', on_delete=models.CASCADE,
        related_name='consortium_memberships')
    status = models.CharField(max_length=30, choices=STATUS_OPTIONS, default='Active')
    joined_on = models.DateField(null=True, blank=True)
    # How this school's students are billed for a section hosted at another
    # member. Read from the *student's* school's membership.
    billing_basis = models.CharField(
        max_length=30, choices=BILLING_BASIS_OPTIONS, default=BILLING_HOST_SCHOOL)

    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['consortium', 'highschool'], name='consortium_member_once'),
        ]

    def __str__(self):
        return f'{self.highschool} in {self.consortium}'
