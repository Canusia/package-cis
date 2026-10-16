from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from cis.models.email_change import EmailChangeRequest
from cis.tests.student_email_change_support import make_student

LIMITS = {'ttl_minutes': 15, 'max_attempts': 5}


class EmailChangeRequestModelTests(TestCase):
    def setUp(self):
        self.student = make_student(email='old@example.com')

    def test_create_for_returns_six_digit_code_and_hashes_it(self):
        req, code = EmailChangeRequest.objects.create_for(self.student, 'New@Example.com', **LIMITS)
        self.assertRegex(code, r'^\d{6}$')
        self.assertNotEqual(req.code_hash, code)
        self.assertEqual(req.new_email, 'new@example.com')
        self.assertEqual(req.old_email, 'old@example.com')
        self.assertEqual(req.status, EmailChangeRequest.PENDING)

    def test_create_for_cancels_prior_pending(self):
        first, _ = EmailChangeRequest.objects.create_for(self.student, 'a@example.com', **LIMITS)
        EmailChangeRequest.objects.create_for(self.student, 'b@example.com', **LIMITS)
        first.refresh_from_db()
        self.assertEqual(first.status, EmailChangeRequest.CANCELLED)

    def test_check_code_success(self):
        req, code = EmailChangeRequest.objects.create_for(self.student, 'a@example.com', **LIMITS)
        self.assertTrue(req.check_code(code))

    def test_wrong_code_decrements_attempts_until_unusable(self):
        req, code = EmailChangeRequest.objects.create_for(self.student, 'a@example.com', **LIMITS)
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(LIMITS['max_attempts']):
            self.assertFalse(req.check_code(wrong))
        self.assertFalse(req.is_usable)
        self.assertFalse(req.check_code(code))  # locked even with right code

    def test_expired_is_unusable(self):
        req, code = EmailChangeRequest.objects.create_for(self.student, 'a@example.com', **LIMITS)
        req.expires_at = timezone.now() - timedelta(seconds=1)
        req.save()
        self.assertFalse(req.is_usable)
        self.assertFalse(req.check_code(code))

    def test_can_resend_after_cooldown(self):
        req, _ = EmailChangeRequest.objects.create_for(self.student, 'a@example.com', **LIMITS)
        self.assertFalse(req.can_resend(60))
        req.sent_at = timezone.now() - timedelta(seconds=61)
        self.assertTrue(req.can_resend(60))
        self.assertFalse(req.can_resend(120))

    def test_limits_come_from_arguments(self):
        req, _ = EmailChangeRequest.objects.create_for(self.student, 'a@example.com', ttl_minutes=30, max_attempts=2)
        self.assertEqual(req.attempts_remaining, 2)
        delta = req.expires_at - req.sent_at
        self.assertEqual(delta, timedelta(minutes=30))

    def test_regenerate_code_invalidates_old_code(self):
        req, old = EmailChangeRequest.objects.create_for(self.student, 'a@example.com', **LIMITS)
        new = req.regenerate_code(ttl_minutes=LIMITS['ttl_minutes'])
        if new != old:
            self.assertFalse(req.check_code(old))
        self.assertTrue(req.check_code(new))

    def test_regenerate_code_does_not_reset_attempts_remaining(self):
        req, code = EmailChangeRequest.objects.create_for(self.student, 'a@example.com', **LIMITS)
        wrong = '000000' if code != '000000' else '111111'
        self.assertFalse(req.check_code(wrong))
        self.assertFalse(req.check_code(wrong))
        remaining_before = req.attempts_remaining
        new_code = req.regenerate_code(ttl_minutes=LIMITS['ttl_minutes'])
        self.assertEqual(req.attempts_remaining, remaining_before)
        req.refresh_from_db()
        self.assertEqual(req.attempts_remaining, remaining_before)
        self.assertTrue(req.check_code(new_code))
