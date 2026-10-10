"""complete_review: decision, account, email and note, in that order."""
from unittest import mock

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from cis.forms.highschool import AccessRequestReviewForm
from cis.models import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorAccessRequest, HSAdministratorPosition,
)
from cis.models.note import HighSchoolNote, HSAdministratorNote
from cis.services.access_request_review import AlreadyDecided, complete_review, note_location

SEND = 'cis.models.highschool_administrator.send_html_mail'
LINK = 'https://reset.example/live-token'


@override_settings(DEBUG=False)
@mock.patch.object(CustomUser, 'get_password_reset_link', return_value=LINK)
class CompleteReviewTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='highschool_admin')
        self.staff = CustomUser.objects.create_superuser(
            username='staff1', email='staff1@example.com', password='x',
            first_name='Sam', last_name='Staff')
        self.hs = HighSchool.objects.create(name='North High', code='NH')
        self.req = HSAdministratorAccessRequest.objects.create(
            name='Jane Doe', email='jane@example.com', phone='555',
            highschool=self.hs, role='Counselor')

    def form(self, decision, message, subject='Hi {{name}}', name='Jane Doe'):
        form = AccessRequestReviewForm({
            'name': name, 'email': 'jane@example.com', 'phone': '555',
            'highschool': str(self.hs.pk), 'role': 'Counselor', 'decide': '1',
            'decision': decision, 'email_subject': subject, 'email_message': message,
        }, instance=self.req)
        self.assertTrue(form.is_valid(), form.errors)
        return form

    def test_approve_grants_sends_edited_text_and_notes_admin(self, _link):
        with mock.patch(SEND) as send:
            outcome = complete_review(
                self.form('approve', 'Welcome! {{password_reset_link}}'), self.staff)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Approved')
        self.assertTrue(HSAdministratorPosition.objects.filter(
            hsadmin__user__email='jane@example.com', highschool=self.hs).exists())
        self.assertEqual(send.call_args.args[1], f'Welcome! {LINK}')
        self.assertTrue(outcome.email_sent and outcome.note_saved)

        note = HSAdministratorNote.objects.get(hsadmin__user__email='jane@example.com')
        self.assertIn('approved', note.note)
        self.assertIn('Sam Staff', note.note)
        self.assertIn('[password reset link]', note.note)
        self.assertNotIn(LINK, note.note)

    def test_deny_without_account_notes_highschool(self, _link):
        with mock.patch(SEND) as send:
            outcome = complete_review(self.form('deny', 'Sorry {{name}}'), self.staff)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Denied')
        self.assertFalse(HSAdministrator.objects.filter(user__email='jane@example.com').exists())
        self.assertEqual(send.call_args.args[1], 'Sorry Jane Doe')
        note = HighSchoolNote.objects.get(highschool=self.hs)
        self.assertIn('denied', note.note)
        self.assertEqual(note_location(self.req)[1], f'/ce/highschool/{self.hs.pk}')
        self.assertTrue(outcome.note_saved)

    def test_deny_with_existing_account_notes_that_admin(self, _link):
        admin = HSAdministrator.create_new('Jane', 'Doe', 'jane@example.com', '555')
        with mock.patch(SEND):
            complete_review(self.form('deny', 'Sorry'), self.staff)
        self.assertTrue(HSAdministratorNote.objects.filter(hsadmin=admin).exists())
        self.assertFalse(HighSchoolNote.objects.filter(highschool=self.hs).exists())

    def test_send_failure_keeps_decision_and_note(self, _link):
        with mock.patch(SEND, side_effect=RuntimeError('smtp down')):
            outcome = complete_review(self.form('deny', 'Sorry'), self.staff)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Denied')
        self.assertFalse(outcome.email_sent)
        self.assertTrue(outcome.note_saved)
        note = HighSchoolNote.objects.get(highschool=self.hs)
        self.assertIn('was not sent', note.note)

    def test_note_failure_keeps_decision_and_email(self, _link):
        with mock.patch(SEND) as send, \
             mock.patch('cis.services.access_request_review._write_note',
                        side_effect=RuntimeError('db')):
            outcome = complete_review(self.form('deny', 'Sorry'), self.staff)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Denied')
        send.assert_called_once()
        self.assertFalse(outcome.note_saved)

    def test_approve_existing_role_warns_and_still_sends(self, _link):
        with mock.patch(SEND):
            complete_review(self.form('approve', '{{password_reset_link}}'), self.staff)
        again = HSAdministratorAccessRequest.objects.create(
            name='Jane Doe', email='jane@example.com', phone='555',
            highschool=self.hs, role='Counselor')
        self.req = again
        with mock.patch(SEND) as send:
            outcome = complete_review(self.form('approve', '{{password_reset_link}}'), self.staff)
        self.assertTrue(outcome.role_already_existed)
        send.assert_called_once()
        self.assertTrue(outcome.note_saved)
        note = HSAdministratorNote.objects.filter(
            hsadmin__user__email='jane@example.com').latest('createdon')
        self.assertIn('Role already existed; permissions unchanged.', note.note)
        self.assertNotIn('Permissions (', note.note)

    def test_note_escapes_email_text_once(self, _link):
        with mock.patch(SEND):
            complete_review(
                self.form('deny', 'Hi\n<script>alert(1)</script>', subject='Hi {{name}}',
                          name="Pat O'Brien & Co"),
                self.staff)
        note = HighSchoolNote.objects.get(highschool=self.hs).note
        self.assertNotIn('<script>', note)
        self.assertNotIn('&lt;script', note)   # tags are stripped, not shown
        self.assertIn('Hi<br>', note)
        self.assertIn('Hi Pat O&#x27;Brien &amp; Co', note)
        self.assertNotIn('&amp;#x27;', note)

    def test_decided_since_form_was_bound_raises_and_changes_nothing(self, _link):
        form = self.form('approve', '{{password_reset_link}}')
        HSAdministratorAccessRequest.objects.filter(pk=self.req.pk).update(status='Denied')
        with mock.patch(SEND) as send:
            with self.assertRaises(AlreadyDecided) as ctx:
                complete_review(form, self.staff)
        self.assertEqual(ctx.exception.status, 'Denied')
        send.assert_not_called()
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, 'Denied')
        self.assertFalse(HSAdministratorNote.objects.exists())
        self.assertFalse(HighSchoolNote.objects.exists())
        self.assertFalse(HSAdministratorPosition.objects.filter(highschool=self.hs).exists())

    def test_note_is_readable_text_from_html_body(self, _link):
        body = 'Line one<br>Line two<br/>\r\nSee <a href="http://x">link</a> now'
        with mock.patch(SEND):
            complete_review(self.form('deny', body), self.staff)
        note = HighSchoolNote.objects.get(highschool=self.hs).note
        self.assertNotIn('&lt;br', note)
        self.assertNotIn('&lt;a', note)
        self.assertNotIn('<a ', note)
        self.assertIn('Line one<br>Line two<br>', note)
        self.assertIn('See link now', note)
