"""Continue-application links (cis.services.continue_application), the
"Send Continue Application Link" staff action and Forgot Password's use of it.

The views that accept the link live in each tenant's student app. Tests that
build a link need its `student:continue_application` route, so they skip on a
tenant that has not taken that host change yet.
"""
import json
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from cis.models.customuser import CustomUser
from cis.models.student import Student
from cis.services import continue_application as ca


def _has_route():
    try:
        reverse('student:continue_application',
                kwargs={'student_id': uuid.uuid4(), 'token': 'x-y'})
        return True
    except NoReverseMatch:
        return False


def _sfx():
    return uuid.uuid4().hex[:8]


def _abandoned(psid=None):
    """The state verify_email leaves: verified, no password, no real id."""
    Group.objects.get_or_create(name='student')
    email = f'ca_{_sfx()}@example.com'
    user = CustomUser(username=email, email=email, psid=psid, first_name='Ann')
    user.save()
    user.groups.add(Group.objects.get(name='student'))
    return Student.objects.create(user=user, account_verified=True)


class _Base(TestCase):
    def setUp(self):
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})


class CanContinueTests(_Base):
    def test_verified_without_password_or_id(self):
        self.assertTrue(ca.can_continue(_abandoned()))

    def test_placeholder_psid_counts_as_no_id(self):
        self.assertTrue(ca.can_continue(_abandoned(psid='-')))

    def test_unverified_cannot_continue(self):
        student = _abandoned()
        student.account_verified = False
        self.assertFalse(ca.can_continue(student))

    def test_password_on_file_cannot_continue(self):
        student = _abandoned()
        student.user.set_password('x')
        self.assertFalse(ca.can_continue(student))

    def test_real_sis_id_cannot_continue(self):
        self.assertFalse(ca.can_continue(_abandoned(psid='H12345')))


class TokenTests(_Base):
    def test_fresh_token_is_valid(self):
        student = _abandoned()
        self.assertTrue(ca.check_token(student, ca.make_token(student)))

    def test_token_expires_after_max_age(self):
        student = _abandoned()
        token = ca.make_token(student)
        later = ca.token_generator._now() + ca.CONTINUE_LINK_MAX_AGE + timedelta(minutes=1)
        with mock.patch.object(ca.token_generator, '_now', return_value=later):
            self.assertFalse(ca.check_token(student, token))

    def test_token_still_valid_just_inside_max_age(self):
        student = _abandoned()
        token = ca.make_token(student)
        later = ca.token_generator._now() + ca.CONTINUE_LINK_MAX_AGE - timedelta(minutes=1)
        with mock.patch.object(ca.token_generator, '_now', return_value=later):
            self.assertTrue(ca.check_token(student, token))

    def test_token_dies_once_signup_finishes(self):
        student = _abandoned()
        token = ca.make_token(student)
        student.user.set_password('pw-12345!')
        student.user.psid = '-'
        student.user.save()
        self.assertFalse(ca.check_token(student, token))

    def test_token_is_bound_to_its_student(self):
        a, b = _abandoned(), _abandoned()
        self.assertFalse(ca.check_token(b, ca.make_token(a)))

    def test_malformed_tokens_are_refused(self):
        student = _abandoned()
        for token in ('', 'nonsense', 'zz-zz-zz', '!-!'):
            self.assertFalse(ca.check_token(student, token), token)


class SendLinkTests(_Base):
    def setUp(self):
        super().setUp()
        if not _has_route():
            self.skipTest('tenant has no student:continue_application route yet')

    def test_sends_the_link_with_built_in_wording(self):
        student = _abandoned()
        self.assertTrue(ca.send_link(student))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [student.user.email])
        self.assertIn(str(student.id), mail.outbox[0].body)
        self.assertIn('3 days', mail.outbox[0].body)
        self.assertTrue(student.studentnote_set.filter(
            note__icontains='continue application link').exists())

    @override_settings(DEBUG=True)
    def test_debug_logs_instead_of_emailing(self):
        self.assertTrue(ca.send_link(_abandoned()))
        self.assertEqual(len(mail.outbox), 0)

    def test_failure_returns_false(self):
        with mock.patch.object(ca, 'make_link', side_effect=RuntimeError):
            self.assertFalse(ca.send_link(_abandoned()))


class StaffActionTests(_Base):
    def setUp(self):
        super().setUp()
        Group.objects.get_or_create(name='ce')
        self.staff = CustomUser.objects.create_user(
            username=f'ce-{_sfx()}', email=f'{_sfx()}@x.com', password='x')
        self.staff.groups.add(Group.objects.get(name='ce'))

    def _run(self, *students):
        from cis.views.student import send_continue_application_link
        req = RequestFactory().post('/x', {'ids[]': [str(s.id) for s in students]})
        req.user = self.staff
        return json.loads(send_continue_application_link(req).content)

    def test_registered_on_detail_and_bulk(self):
        import cis.views.student  # noqa: F401  (registers the actions)
        from myce.component_registry.student import student_actions
        for scope in ('detail', 'bulk'):
            actions = student_actions.for_scope(scope)['verification']['actions']
            self.assertEqual(actions['send_continue_application_link']['label'],
                             'Send Continue Application Link')

    def test_mixed_selection(self):
        unverified = _abandoned()
        unverified.account_verified = False
        unverified.save()
        continuing = _abandoned()
        finished = _abandoned(psid='H99999')
        with mock.patch.object(Student, 'send_verification_request_email') as verify, \
                mock.patch.object(ca, 'send_link', return_value=True) as send:
            result = self._run(unverified, continuing, finished)
        verify.assert_called_once()
        send.assert_called_once()
        self.assertIn(continuing.user.email, result['message'])
        self.assertIn('Skipped', result['message'])
        self.assertIn(finished.user.email, result['message'])
        self.assertEqual(result['status'], 'success')

    def test_failed_send_is_reported(self):
        student = _abandoned()
        with mock.patch.object(ca, 'send_link', return_value=False):
            result = self._run(student)
        self.assertIn('Could not send', result['message'])
        self.assertEqual(result['status'], 'warning')


class ForgotPasswordTests(_Base):
    def _reset(self, email):
        # save() only, past the form's captcha: the branch under test is in save.
        from cis.views.password_management import cisPasswordResetForm
        req = RequestFactory().post('/x')
        form = cisPasswordResetForm(req)
        form.cleaned_data = {'email': email}
        form.save(request=req)

    def test_abandoned_student_gets_continue_link_and_stays_verified(self):
        student = _abandoned()
        with mock.patch.object(ca, 'send_link', return_value=True) as send, \
                mock.patch.object(Student, 'send_verification_request_email') as verify:
            self._reset(student.user.email)
        send.assert_called_once()
        verify.assert_not_called()
        student.refresh_from_db()
        self.assertTrue(student.account_verified)

    def test_falls_back_to_verification_when_link_cannot_be_sent(self):
        student = _abandoned()
        with mock.patch.object(ca, 'send_link', return_value=False), \
                mock.patch.object(Student, 'send_verification_request_email') as verify:
            self._reset(student.user.email)
        verify.assert_called_once()
        student.refresh_from_db()
        self.assertFalse(student.account_verified)
