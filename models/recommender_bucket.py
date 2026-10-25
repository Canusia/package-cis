"""Last-name buckets that split a high school's recommendation caseload.

A bucket is a whole-letter range of student last names (A–F, G–Z, …) defined
per high school. An HS admin position holding the recommendation permission
may be assigned to buckets; it then covers only students whose last-name
initial falls in one of them. A position with no buckets covers the whole
school — the behaviour before buckets existed, and the fallback for any
student no bucket covers. The rules live in cis.services.recommender_scope.
"""
import string
import uuid

from django.db import models
from django.db.models import F, Q

LETTERS = tuple(string.ascii_uppercase)
LETTER_CHOICES = [(c, c) for c in LETTERS]


class RecommenderBucket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    highschool = models.ForeignKey(
        'cis.HighSchool', on_delete=models.PROTECT, related_name='recommender_buckets')
    name = models.CharField(max_length=100)
    start_letter = models.CharField(max_length=1, choices=LETTER_CHOICES)
    end_letter = models.CharField(max_length=1, choices=LETTER_CHOICES)

    created_at = models.DateTimeField(auto_now_add=True)
    last_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_letter', 'end_letter', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['highschool', 'name'], name='recbucket_unique_name'),
            models.CheckConstraint(
                condition=Q(start_letter__lte=F('end_letter')),
                name='recbucket_start_lte_end'),
            models.CheckConstraint(
                condition=Q(start_letter__regex=r'^[A-Z]$', end_letter__regex=r'^[A-Z]$'),
                name='recbucket_letters_a_z'),
        ]

    def __str__(self):
        return f'{self.name} ({self.range_label})'

    @property
    def range_label(self):
        if self.start_letter == self.end_letter:
            return self.start_letter
        return f'{self.start_letter}–{self.end_letter}'

    def covers(self, initial):
        return bool(initial) and self.start_letter <= initial <= self.end_letter

    def letters(self):
        return LETTERS[LETTERS.index(self.start_letter):LETTERS.index(self.end_letter) + 1]
