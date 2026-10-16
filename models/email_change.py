"""EmailChangeRequest: a pending student self-service email change (#79).

A 6-digit code goes to the new address; the change completes only when the
student enters it. The code is stored as an HMAC (keyed by SECRET_KEY and the
request id), compared in constant time, and attempts are consumed with a
guarded UPDATE so two concurrent guesses cannot both spend the same attempt.

Ported from nnu#15 / ewu#80 (student app) into cis.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone


def _hash_code(request_id, code):
    msg = f'{request_id}:{code}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def _new_code():
    return f'{secrets.randbelow(1_000_000):06d}'


class EmailChangeRequestManager(models.Manager):
    def create_for(self, student, new_email, *, ttl_minutes, max_attempts):
        self.filter(student=student, status=EmailChangeRequest.PENDING).update(
            status=EmailChangeRequest.CANCELLED)
        req = self.model(
            student=student,
            old_email=student.user.email,
            new_email=new_email.strip().lower(),
        )
        code = req._set_code(ttl_minutes, max_attempts)
        req.save()
        return req, code


class EmailChangeRequest(models.Model):
    PENDING = 'pending'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [(PENDING, 'Pending'), (COMPLETED, 'Completed'), (CANCELLED, 'Cancelled')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey('cis.Student', on_delete=models.CASCADE, related_name='email_change_requests')
    old_email = models.EmailField()
    new_email = models.EmailField()
    code_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    attempts_remaining = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = EmailChangeRequestManager()

    class Meta:
        ordering = ['-created_at']

    def _set_code(self, ttl_minutes, max_attempts):
        code = _new_code()
        now = timezone.now()
        self.code_hash = _hash_code(self.id, code)
        self.sent_at = now
        self.expires_at = now + timedelta(minutes=ttl_minutes)
        self.attempts_remaining = max_attempts
        return code

    def regenerate_code(self, *, ttl_minutes):
        code = _new_code()
        now = timezone.now()
        self.code_hash = _hash_code(self.id, code)
        self.sent_at = now
        self.expires_at = now + timedelta(minutes=ttl_minutes)
        self.save(update_fields=['code_hash', 'sent_at', 'expires_at'])
        return code

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self):
        return self.status == self.PENDING and not self.is_expired and self.attempts_remaining > 0

    def can_resend(self, cooldown_seconds):
        return (timezone.now() - self.sent_at).total_seconds() >= cooldown_seconds

    def check_code(self, code):
        updated = EmailChangeRequest.objects.filter(
            pk=self.pk, status=self.PENDING, attempts_remaining__gt=0,
            expires_at__gt=timezone.now(),
        ).update(attempts_remaining=F('attempts_remaining') - 1)
        if updated == 0:
            self.refresh_from_db(fields=['attempts_remaining', 'status'])
            return False
        if hmac.compare_digest(self.code_hash, _hash_code(self.id, (code or '').strip())):
            return True
        self.refresh_from_db(fields=['attempts_remaining'])
        return False
