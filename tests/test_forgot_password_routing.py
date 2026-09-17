"""Which of the two things Forgot Password does to a student.

For a student who never stored a password there is nothing to reset, so the
form re-issues a verification link instead -- which flips the account back to
unverified. That is the right repair for an abandoned signup and destructive
for anything else, so the branch has to be exact.

It used to key off psid: `not has_usable_password() or psid in ['', None]`.
Both halves are wrong. has_usable_password() answers True for the *empty*
password an abandoned signup actually carries, and a NULL psid is normal for a
CSV-imported student who has a real password and is only waiting on an SIS id
-- so imported students who clicked "Forgot Password" were silently
un-verified and handed a verification link they did not need.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.test import TestCase

from cis.models.settings import Setting
from cis.models.student import Student
from cis.views.password_management import cisPasswordResetForm

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class ForgotPasswordRoutingTests(TestCase):
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

    def _student(self, *, psid, password='x', verified=True):
        # password=None reproduces StudentVerifyEmailForm.save(), which never
        # calls set_password: the column is left empty, not unusable.
        user = User(username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com',
                    psid=psid)
        if password is not None:
            user.set_password(password)
        user.save()
        user.groups.add(Group.objects.get(name='student'))
        return Student.objects.create(
            user=user, account_verified=verified, verification_id=None,
            meta={})

    def _forgot(self, student):
        form = cisPasswordResetForm(request=None)
        form.cleaned_data = {'email': student.user.email}
        return form.save()

    def test_orphan_is_re_issued_a_verification_link(self):
        # Verified, no password ever stored: the account cannot be logged into,
        # so a reset link would be useless. This is the state the branch exists
        # for, and flipping it back to unverified is the intended repair.
        student = self._student(psid=None, password=None)
        self._forgot(student)

        student.refresh_from_db()
        self.assertFalse(student.account_verified)
        self.assertIsNotNone(student.verification_id)
        self.assertEqual(len(mail.outbox), 1)

    def test_imported_student_keeps_their_verified_account(self):
        # Real password, NULL psid until the SIS assigns one. Nothing about
        # this account is broken; it must not be touched.
        student = self._student(psid=None)
        self._forgot(student)

        student.refresh_from_db()
        self.assertTrue(student.account_verified)
        self.assertIsNone(student.verification_id)

    def test_imported_student_gets_a_real_password_reset(self):
        student = self._student(psid=None)
        self._forgot(student)

        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('Verify your email', mail.outbox[0].subject)

    def test_student_awaiting_a_sis_id_is_untouched(self):
        student = self._student(psid='-')
        self._forgot(student)

        student.refresh_from_db()
        self.assertTrue(student.account_verified)
        self.assertIsNone(student.verification_id)

    def test_provisioned_student_is_untouched(self):
        student = self._student(psid='H1234567')
        self._forgot(student)

        student.refresh_from_db()
        self.assertTrue(student.account_verified)
        self.assertIsNone(student.verification_id)

    def test_student_with_a_sis_id_but_no_password_gets_a_reset(self):
        # The commonest shape in this database: a real SIS id and no MyCE
        # password, because the account was provisioned rather than self-signed
        # -up. A reset link works perfectly well against an empty password.
        # Sending a verification link instead strands them: complete_signup
        # turns away anyone holding a psid, so the link leads nowhere.
        student = self._student(psid='H1234567', password=None)
        self._forgot(student)

        student.refresh_from_db()
        self.assertIsNone(student.verification_id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('Verify your email', mail.outbox[0].subject)

    def test_unverified_student_with_a_sis_id_keeps_their_verified_flag(self):
        # Same shape, unverified -- which is how all 179 such rows currently
        # sit. reset_verification_id() must not fire for them either.
        student = self._student(psid='H1234567', password=None, verified=False)
        self._forgot(student)

        student.refresh_from_db()
        self.assertIsNone(student.verification_id)
