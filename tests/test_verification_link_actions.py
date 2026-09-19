"""The Send/Get Verification Link bulk actions must reach abandoned accounts.

Both actions filtered account_verified=False. An account that verified its
email and then abandoned before setting a password is account_verified=True, so
both returned "No students pending account verification found" -- leaving
admins with no tool for the exact population they were being asked to rescue.
And because verification_id is nulled on verify, reaching that student without
re-issuing a token would have handed out a dead link.

The selection has to be narrow in the other direction too: re-issuing a token
un-verifies the account, so anything it picks up by mistake is damaged. A NULL
psid alone does not mark an abandoned signup -- CSV-imported students carry one
too -- which is why the absence of a stored password is part of the test.
"""
import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import RequestFactory, TestCase

from cis.models.settings import Setting
from cis.models.student import Student
from cis.views.student import (
    _students_needing_verification_link, get_verification_link,
    resend_verification_link,
)

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class _StudentStates:
    """Fixtures shared by both suites. A plain mixin, not a TestCase: making
    the action suite a subclass of the selection suite would re-run all of its
    tests a second time."""

    def setUp(self):
        Group.objects.get_or_create(name='student')
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@x.com'})

        from cis.settings.registration_email import registration_email
        Setting.objects.update_or_create(
            key=registration_email.key,
            defaults={'value': {
                'is_active': 'Yes',
                'verify_email_subject': 'Verify your email',
                'verification_email': 'Follow {{verification_link}} to continue.',
            }},
        )

        self.unverified = self._student(verified=False, psid=None,
                                        token=uuid.uuid4(), password=None)
        # verified, never finished the application -> token was consumed
        self.orphan = self._student(verified=True, psid=None, token=None,
                                    password=None)
        self.orphan_blank_psid = self._student(verified=True, psid='',
                                               token=None, password=None)
        # finished the application, waiting on the SIS id
        self.awaiting_sis = self._student(verified=True, psid='-', token=None)
        # fully provisioned
        self.provisioned = self._student(verified=True, psid='H1234567',
                                         token=None)
        # Created by the CSV importer: verified, a real (random) password, and
        # no psid until the SIS assigns one. Looks like an orphan on psid
        # alone, and must never be touched by these actions.
        self.imported = self._student(verified=True, psid=None, token=None)

    def _student(self, *, verified, psid, token, password='x'):
        # password=None reproduces StudentVerifyEmailForm.save(), which never
        # calls set_password: the column is left *empty*, which is not the same
        # as unusable and is exactly what has_usable_password() gets wrong.
        user = User(username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com',
                    psid=psid)
        if password is not None:
            user.set_password(password)
        user.save()
        return Student.objects.create(
            user=user, account_verified=verified, verification_id=token,
            meta={})

    def _select(self, *students):
        """Every student the actions would act on, live link or not."""
        live, needs_token = self._split(*students)
        return live + needs_token

    def _split(self, *students):
        return _students_needing_verification_link(
            [str(s.id) for s in students])


class VerificationLinkSelectionTests(_StudentStates, TestCase):
    """Which students the two actions consider at all."""

    # --- selection -----------------------------------------------------------

    def test_orphan_is_selected(self):
        selected = self._select(self.orphan)
        self.assertEqual([s.id for s in selected], [self.orphan.id])

    def test_orphan_with_blank_psid_is_selected(self):
        selected = self._select(self.orphan_blank_psid)
        self.assertEqual([s.id for s in selected], [self.orphan_blank_psid.id])

    def test_unverified_student_is_still_selected(self):
        selected = self._select(self.unverified)
        self.assertEqual([s.id for s in selected], [self.unverified.id])

    def test_student_awaiting_sis_id_is_excluded(self):
        # They completed the application and have a password; Forgot Password
        # is their route, not a new verification link.
        self.assertEqual(self._select(self.awaiting_sis), [])

    def test_provisioned_student_is_excluded(self):
        self.assertEqual(self._select(self.provisioned), [])

    def test_imported_student_is_excluded(self):
        # Verified with a real password and a NULL psid. Selecting on psid
        # alone swept these up, and the selection itself un-verifies whatever
        # it returns -- so a CE admin bulk-selecting imported students and
        # choosing 'Get Verification Link', which reads as a lookup, silently
        # broke correctly provisioned accounts.
        self.assertEqual(self._select(self.imported), [])

    def test_imported_student_is_left_untouched(self):
        self._select(self.imported)
        self.imported.refresh_from_db()
        self.assertTrue(self.imported.account_verified)
        self.assertIsNone(self.imported.verification_id)

    def test_mixed_selection_keeps_only_the_eligible(self):
        selected = self._select(
            self.unverified, self.orphan, self.awaiting_sis, self.provisioned,
            self.imported)
        self.assertEqual(
            {s.id for s in selected}, {self.unverified.id, self.orphan.id})

    def test_unknown_id_is_ignored(self):
        self.assertEqual(
            _students_needing_verification_link([str(uuid.uuid4())]), ([], []))

    def test_selection_splits_live_links_from_ones_needing_a_token(self):
        live, needs_token = self._split(self.unverified, self.orphan)
        self.assertEqual([s.id for s in live], [self.unverified.id])
        self.assertEqual([s.id for s in needs_token], [self.orphan.id])

    # --- selecting writes nothing -------------------------------------------

    def test_selection_alone_never_mints_a_token(self):
        # Minting is reset_verification_id(): it un-verifies the account and
        # invalidates any link already emailed. Only the action that sends a
        # new link may do that, so the selection itself stays read-only.
        self._select(self.orphan)
        self.orphan.refresh_from_db()
        self.assertTrue(self.orphan.account_verified)
        self.assertIsNone(self.orphan.verification_id)

    def test_existing_token_of_an_unverified_student_is_preserved(self):
        original = self.unverified.verification_id
        live, _ = self._split(self.unverified)
        self.assertEqual(live[0].verification_id, original)


class VerificationLinkActionTests(_StudentStates, TestCase):
    """Which of the two actions is allowed to write."""

    def _post(self, action, *students):
        request = RequestFactory().post(
            '/', {'ids[]': [str(s.id) for s in students]})
        request.user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        return json.loads(action(request).content)['message']

    # --- 'Send Verification Link' mints, because it emails a new link -------

    def test_send_flips_the_orphan_back_to_unverified(self):
        # reset_verification_id() clears account_verified so the student can
        # walk the verify_email -> complete_signup flow again.
        self._post(resend_verification_link, self.orphan)
        self.orphan.refresh_from_db()
        self.assertFalse(self.orphan.account_verified)
        self.assertIsNotNone(self.orphan.verification_id)

    def test_send_emails_the_orphan(self):
        before = len(mail.outbox)
        self._post(resend_verification_link, self.orphan)
        self.assertGreater(len(mail.outbox), before)

    def test_send_leaves_a_live_token_alone(self):
        original = self.unverified.verification_id
        self._post(resend_verification_link, self.unverified)
        self.unverified.refresh_from_db()
        self.assertEqual(self.unverified.verification_id, original)

    def test_send_failure_for_one_student_still_sends_to_the_rest(self):
        # send_verification_request_email() raises KeyError when a tenant has
        # not registered the registration_email setting. Tokens used to be
        # minted for the whole selection up front, so one raise left every
        # remaining student un-verified with no email on the way.
        real_send = Student.send_verification_request_email

        def send(student):
            if student.id == self.orphan.id:
                raise KeyError('registration_email')
            return real_send(student)

        before = len(mail.outbox)
        with mock.patch.object(Student, 'send_verification_request_email',
                               autospec=True, side_effect=send):
            message = self._post(
                resend_verification_link, self.orphan, self.orphan_blank_psid)

        self.assertEqual(len(mail.outbox), before + 1)
        self.assertIn('Could not send to', message)
        self.assertIn(self.orphan.user.email, message)

    def test_send_when_every_student_fails_does_not_claim_none_were_found(self):
        # The students were found; sending to them failed. Saying "No students
        # needing account verification found" would send the admin looking for
        # a selection problem that does not exist.
        with mock.patch.object(Student, 'send_verification_request_email',
                               autospec=True,
                               side_effect=KeyError('registration_email')):
            message = self._post(resend_verification_link, self.orphan)
        self.assertNotIn('No students needing', message)
        self.assertIn('Could not send to', message)
        self.assertIn(self.orphan.user.email, message)

    def test_send_escapes_addresses_in_the_alert(self):
        # The message is rendered as HTML in the admin's alert modal, and a
        # quoted local part may legally contain < and >.
        self.orphan.user.email = '"<b>x</b>"@example.com'
        self.orphan.user.save()
        message = self._post(resend_verification_link, self.orphan)
        self.assertNotIn('<b>x</b>', message)
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', message)

    # --- 'Get Verification Link' is read-only -------------------------------

    def test_get_does_not_touch_the_orphan(self):
        # The regression: 'Get' reads as "show me the URL", but it ran the same
        # reset as 'Send' -- and it is a bulk action, so a select-all would
        # un-verify every matching row at once, with no confirmation.
        self._post(get_verification_link, self.orphan)
        self.orphan.refresh_from_db()
        self.assertTrue(self.orphan.account_verified)
        self.assertIsNone(self.orphan.verification_id)

    def test_get_sends_no_email(self):
        before = len(mail.outbox)
        self._post(get_verification_link, self.orphan)
        self.assertEqual(len(mail.outbox), before)

    def test_get_names_the_students_it_cannot_show_a_link_for(self):
        message = self._post(get_verification_link, self.orphan)
        self.assertIn(str(self.orphan), message)
        self.assertIn('Send Verification Link', message)

    def test_get_shows_a_live_link_without_changing_it(self):
        original = self.unverified.verification_id
        message = self._post(get_verification_link, self.unverified)
        self.assertIn(str(original), message)
        self.unverified.refresh_from_db()
        self.assertEqual(self.unverified.verification_id, original)

    def test_get_reports_both_kinds_in_one_message(self):
        message = self._post(
            get_verification_link, self.unverified, self.orphan)
        self.assertIn(str(self.unverified.verification_id), message)
        self.assertIn(str(self.orphan), message)
