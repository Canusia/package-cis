from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from cis.models.note import StudentNote
from cis.models.settings import Setting
from cis.settings.student_email_change import student_email_change, DEFAULTS
from cis.models.email_change import EmailChangeRequest
from cis.services import student_email_change as svc
from cis.tests.student_email_change_support import make_student

User = get_user_model()
SEND = 'cis.services.student_email_change.send_html_mail'


class StartEmailChangeTests(TestCase):
    def setUp(self):
        self.student = make_student(email='old@example.com')

    @mock.patch(SEND)
    def test_sends_code_to_new_address_only(self, send):
        req = svc.start_email_change(self.student, 'new@example.com')
        self.assertEqual(req.new_email, 'new@example.com')
        send.assert_called_once()
        args = send.call_args.args
        self.assertEqual(args[4], ['new@example.com'])
        self.assertRegex(args[1], r'\d{6}')  # code in text body

    @mock.patch(SEND)
    def test_rejects_same_email(self, send):
        with self.assertRaises(svc.EmailChangeError):
            svc.start_email_change(self.student, 'OLD@example.com')
        send.assert_not_called()

    @mock.patch(SEND)
    def test_rejects_email_used_by_another_user(self, send):
        make_student(email='taken@example.com')
        with self.assertRaises(svc.EmailChangeError):
            svc.start_email_change(self.student, 'taken@example.com')

    @mock.patch(SEND)
    def test_rejects_email_used_as_secondary(self, send):
        other = make_student(email='x@example.com')
        other.user.secondary_email = 'sec@example.com'
        other.user.save()
        with self.assertRaises(svc.EmailChangeError):
            svc.start_email_change(self.student, 'sec@example.com')

    @mock.patch(SEND)
    def test_resend_blocked_during_cooldown(self, send):
        req = svc.start_email_change(self.student, 'new@example.com')
        with self.assertRaises(svc.EmailChangeError):
            svc.resend_code(req)

    @mock.patch(SEND)
    def test_blocked_while_application_in_review(self, send):
        self.student.application_status = 'in_review'
        self.student.save()
        with self.assertRaises(svc.EmailChangeError):
            svc.start_email_change(self.student, 'new@example.com')
        send.assert_not_called()

    @mock.patch(SEND)
    def test_limits_read_from_setting(self, send):
        Setting.objects.create(key=student_email_change.key, value={
            **DEFAULTS, 'code_ttl_minutes': 30, 'max_attempts': 2, 'resend_cooldown_seconds': 0,
            'max_requests_per_day': 5})
        req = svc.start_email_change(self.student, 'new@example.com')
        self.assertEqual(req.attempts_remaining, 2)
        self.assertEqual(req.expires_at - req.sent_at, timedelta(minutes=30))
        svc.resend_code(req)  # cooldown 0 -> allowed immediately
        self.assertEqual(send.call_count, 2)

    @mock.patch(SEND)
    def test_start_twice_within_cooldown_blocked(self, send):
        svc.start_email_change(self.student, 'new@example.com')
        with self.assertRaises(svc.EmailChangeError):
            svc.start_email_change(self.student, 'another@example.com')

    @mock.patch(SEND)
    def test_start_blocked_after_daily_limit_reached(self, send):
        Setting.objects.create(key=student_email_change.key, value={
            **DEFAULTS, 'resend_cooldown_seconds': 0, 'max_requests_per_day': 2})
        svc.start_email_change(self.student, 'first@example.com')
        svc.start_email_change(self.student, 'second@example.com')
        with self.assertRaises(svc.EmailChangeError):
            svc.start_email_change(self.student, 'third@example.com')

    @mock.patch(SEND)
    def test_resend_after_wrong_guesses_keeps_reduced_attempts(self, send):
        Setting.objects.create(key=student_email_change.key, value={
            **DEFAULTS, 'resend_cooldown_seconds': 0})
        req = svc.start_email_change(self.student, 'new@example.com')
        wrong = '000000'
        req.check_code(wrong)
        req.check_code(wrong)
        remaining_before = req.attempts_remaining
        svc.resend_code(req)
        req.refresh_from_db()
        self.assertEqual(req.attempts_remaining, remaining_before)


class ConfirmEmailChangeTests(TestCase):
    def setUp(self):
        self.student = make_student(email='old@example.com')
        self.req, self.code = EmailChangeRequest.objects.create_for(
            self.student, 'new@example.com', ttl_minutes=15, max_attempts=5)

    @mock.patch(SEND)
    def test_success_updates_user_note_and_confirmations(self, send):
        with self.captureOnCommitCallbacks(execute=True):
            svc.confirm_email_change(self.req, self.code, actor=self.student.user)

        user = User.objects.get(pk=self.student.user.pk)
        self.assertEqual(user.email, 'new@example.com')
        self.assertEqual(user.username, 'new@example.com')

        self.req.refresh_from_db()
        self.assertEqual(self.req.status, EmailChangeRequest.COMPLETED)
        self.assertIsNotNone(self.req.completed_at)

        note = StudentNote.objects.get(student=self.student)
        self.assertEqual(note.meta, {'type': 'private'})
        self.assertIn('old@example.com', note.note)
        self.assertIn('new@example.com', note.note)

        recipients = sorted(c.args[4][0] for c in send.call_args_list)
        self.assertEqual(recipients, ['new@example.com', 'old@example.com'])

        self.student.refresh_from_db()
        self.assertIsNotNone(self.student.profile_dirty_at)

    @mock.patch(SEND)
    def test_confirm_blocked_if_application_went_into_review(self, send):
        self.student.application_status = 'in_review'
        self.student.save()
        with self.assertRaises(svc.EmailChangeError):
            svc.confirm_email_change(self.req, self.code, actor=self.student.user)
        self.student.user.refresh_from_db()
        self.assertEqual(self.student.user.email, 'old@example.com')

    @mock.patch(SEND)
    def test_wrong_code_changes_nothing(self, send):
        wrong = '000000' if self.code != '000000' else '111111'
        with self.assertRaises(svc.EmailChangeError):
            svc.confirm_email_change(self.req, wrong, actor=self.student.user)
        self.student.user.refresh_from_db()
        self.assertEqual(self.student.user.email, 'old@example.com')
        self.student.refresh_from_db()
        self.assertIsNone(self.student.profile_dirty_at)
        self.assertFalse(StudentNote.objects.filter(student=self.student).exists())
        send.assert_not_called()

    @mock.patch(SEND)
    def test_email_taken_between_request_and_confirm(self, send):
        make_student(email='new@example.com')
        with self.assertRaises(svc.EmailChangeError):
            svc.confirm_email_change(self.req, self.code, actor=self.student.user)
        self.student.user.refresh_from_db()
        self.assertEqual(self.student.user.email, 'old@example.com')

    @mock.patch(SEND)
    def test_confirm_blocked_if_request_already_completed(self, send):
        # Update the row directly (not self.req) to simulate a concurrent
        # confirm that already completed this request.
        EmailChangeRequest.objects.filter(pk=self.req.pk).update(status=EmailChangeRequest.COMPLETED)
        with self.assertRaises(svc.EmailChangeError):
            svc.confirm_email_change(self.req, self.code, actor=self.student.user)
        self.student.user.refresh_from_db()
        self.assertEqual(self.student.user.email, 'old@example.com')

    @mock.patch('cis.services.student_email_change.CustomUser.save', side_effect=IntegrityError)
    @mock.patch(SEND)
    def test_integrity_error_on_save_is_handled(self, send, save_mock):
        with self.assertRaises(svc.EmailChangeError):
            svc.confirm_email_change(self.req, self.code, actor=self.student.user)
        self.student.user.refresh_from_db()
        self.assertEqual(self.student.user.email, 'old@example.com')
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, EmailChangeRequest.PENDING)

    @mock.patch(SEND)
    def test_login_works_with_new_email(self, send):
        with self.captureOnCommitCallbacks(execute=True):
            svc.confirm_email_change(self.req, self.code, actor=self.student.user)
        from django.contrib.auth import authenticate
        self.assertIsNotNone(authenticate(username='new@example.com', password='pw-12345!'))
