import re
from importlib import import_module
from unittest import mock

from django.conf import settings
from django.http import HttpRequest
from django.test import TestCase, override_settings
from django.urls import reverse

from cis.models.email_change import EmailChangeRequest
from cis.models.term import AcademicYear, Term
from cis.settings.menu import menu as menu_settings
from cis.tests.student_email_change_support import (
    PASSWORD, make_student, templates_with_stubs,
)

SEND = 'cis.services.student_email_change.send_html_mail'


def _session_login(client, user):
    """Session-login to avoid django_login_history's post_login signal
    crash (no usable REMOTE_ADDR on a force_login request) and the
    student_onboarding term-rollover signal that fires on real logins."""
    engine = import_module(settings.SESSION_ENGINE)
    session = engine.SessionStore()
    session['_auth_user_id'] = str(user.pk)
    session['_auth_user_backend'] = 'cis.email_backend.EmailAuthBackend'
    session['_auth_user_hash'] = user.get_session_auth_hash()
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


@override_settings(ROOT_URLCONF='cis.tests.student_email_change_urls',
                   TEMPLATES=templates_with_stubs())
class ChangeEmailViewTests(TestCase):
    def setUp(self):
        # Tenant context processors (e.g. student_onboarding's) need a
        # resolvable "current term"; draw_menu reads the cis menu Setting.
        ay = AcademicYear.objects.create(name='AY26')
        Term.objects.create(academic_year=ay, label='Spring', code='S26')
        menu_settings(HttpRequest()).install()
        self.student = make_student(email='old@example.com')
        _session_login(self.client, self.student.user)
        self.url = reverse('student:change_email')

    def _request_code(self, new_email='new@example.com', password=PASSWORD, **kw):
        return self.client.post(
            self.url,
            {'new_email': new_email, 'current_password': password, 'request_code': '1'}, **kw)

    def test_anonymous_redirected(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_user_without_student_record_redirected(self):
        from django.contrib.auth import get_user_model
        other = get_user_model().objects.create_user(
            username='staff@example.com', email='staff@example.com', password=PASSWORD)
        _session_login(self.client, other)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_get_shows_request_step(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="request_code"')
        self.assertContains(r, reverse('student:profile'))

    @mock.patch(SEND)
    def test_request_code_moves_to_verify_step(self, send):
        r = self._request_code(follow=True)
        self.assertContains(r, 'name="verify_code"')
        self.assertContains(r, 'new@example.com')
        self.assertTrue(EmailChangeRequest.objects.filter(student=self.student, status='pending').exists())

    @mock.patch(SEND)
    def test_duplicate_email_shows_error(self, send):
        make_student(email='taken@example.com')
        r = self._request_code('taken@example.com')
        self.assertContains(r, 'already registered')
        send.assert_not_called()

    @mock.patch(SEND)
    def test_wrong_current_password_shows_error_and_creates_no_request(self, send):
        r = self._request_code(password='wrong-password')
        self.assertContains(r, 'incorrect')
        self.assertFalse(EmailChangeRequest.objects.filter(student=self.student).exists())
        send.assert_not_called()

    @mock.patch(SEND)
    def test_full_flow_changes_email(self, send):
        self._request_code()
        EmailChangeRequest.objects.get(student=self.student, status='pending')
        text_body = send.call_args.args[1]
        code = re.search(r'\d{6}', text_body).group()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url, {'code': code, 'verify_code': '1'}, follow=True)
        self.student.user.refresh_from_db()
        self.assertEqual(self.student.user.email, 'new@example.com')
        self.assertNotIn('email_change_request_id', self.client.session)
        self.assertEqual(r.redirect_chain[-1][0], reverse('student:profile'))
        self.assertContains(r, 'new@example.com')

    @mock.patch(SEND)
    def test_cannot_use_another_students_request(self, send):
        other = make_student(email='other@example.com')
        other_req, _ = EmailChangeRequest.objects.create_for(
            other, 'hijack@example.com', ttl_minutes=15, max_attempts=5)
        session = self.client.session
        session['email_change_request_id'] = str(other_req.id)
        session.save()
        r = self.client.get(self.url)
        self.assertContains(r, 'name="request_code"')  # falls back to step 1

    @mock.patch(SEND)
    def test_resend_with_no_pending_shows_error(self, send):
        r = self.client.post(self.url, {'resend_code': '1'}, follow=True)
        self.assertContains(r, 'no longer active')

    @mock.patch(SEND)
    def test_verify_with_no_pending_shows_error(self, send):
        r = self.client.post(self.url, {'code': '123456', 'verify_code': '1'}, follow=True)
        self.assertContains(r, 'no longer active')

    @mock.patch(SEND)
    def test_in_review_shows_locked_message_and_no_form(self, send):
        self.student.application_status = 'in_review'
        self.student.save()
        r = self.client.get(self.url)
        self.assertContains(r, 'under review')
        self.assertNotContains(r, 'name="request_code"')
        self._request_code()
        self.assertFalse(EmailChangeRequest.objects.filter(student=self.student).exists())
        send.assert_not_called()

    @mock.patch(SEND)
    def test_cancel_clears_pending(self, send):
        self._request_code()
        self.client.post(self.url, {'cancel': '1'})
        self.assertFalse(EmailChangeRequest.objects.filter(student=self.student, status='pending').exists())


class ChangeEmailTemplateTests(TestCase):
    def test_template_has_no_multiline_hash_comments(self):
        from django.template.loader import get_template
        source = get_template('cis/student/change_email.html').template.source
        self.assertNotRegex(source, r'\{#[^#]*\n')
