"""#20: "Mark as UnVerified" must only reach abandoned signups.

A verified student with no psid is either an abandoned signup (clicked the
verification link, never set a password) or a CSV-imported student (real
password, waiting on an SIS id). Only the first should be flipped back to
unverified; the password tells them apart, psid does not.
"""
import json
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.models.customuser import no_login_password_q
from cis.models.student import Student
from cis.views.student import mark_as_unverified

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class HasLoginPasswordTests(TestCase):
    def _user(self, password):
        user = User.objects.create(
            username=f'u_{_sfx()}', email=f'u_{_sfx()}@x.com')
        User.objects.filter(pk=user.pk).update(password=password)
        user.refresh_from_db()
        return user

    def test_empty_password_cannot_log_in(self):
        user = self._user('')
        self.assertFalse(user.has_login_password())
        self.assertTrue(User.objects.filter(
            no_login_password_q(''), pk=user.pk).exists())

    def test_unusable_password_cannot_log_in(self):
        user = User.objects.create(username=f'u_{_sfx()}', email=f'u_{_sfx()}@x.com')
        user.set_unusable_password()
        user.save()
        self.assertFalse(user.has_login_password())
        self.assertTrue(User.objects.filter(
            no_login_password_q(''), pk=user.pk).exists())

    def test_real_password_can_log_in(self):
        user = User.objects.create_user(
            username=f'u_{_sfx()}', email=f'u_{_sfx()}@x.com', password='Real-pass-12')
        self.assertTrue(user.has_login_password())
        self.assertFalse(User.objects.filter(
            no_login_password_q(''), pk=user.pk).exists())


class MarkAsUnverifiedTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.admin = User.objects.create_superuser(
            username=f'su_{_sfx()}', email=f'su_{_sfx()}@x.com', password='x')

        # Clicked the verification link, never set a password.
        abandoned_user = User.objects.create(
            username=f'ab_{_sfx()}', email=f'ab_{_sfx()}@x.com', password='')
        self.abandoned = Student.objects.create(
            user=abandoned_user, account_verified=True)

        # CSV importer: verified, real password, psid not assigned yet.
        imported_user = User.objects.create_user(
            username=f'im_{_sfx()}', email=f'im_{_sfx()}@x.com',
            password='Random-pass-12')
        self.imported = Student.objects.create(
            user=imported_user, account_verified=True)

    def _run(self, *students):
        request = RequestFactory().post(
            '/x', {'ids[]': [str(s.id) for s in students]})
        request.user = self.admin
        return json.loads(mark_as_unverified(request).content)

    def test_abandoned_signup_is_unverified(self):
        self._run(self.abandoned)
        self.abandoned.refresh_from_db()
        self.assertFalse(self.abandoned.account_verified)

    def test_imported_student_is_left_verified(self):
        result = self._run(self.imported)
        self.imported.refresh_from_db()
        self.assertTrue(self.imported.account_verified)
        self.assertEqual(result['status'], 'warning')

    def test_select_all_flips_only_the_abandoned_signup(self):
        self._run(self.abandoned, self.imported)
        self.abandoned.refresh_from_db()
        self.imported.refresh_from_db()
        self.assertFalse(self.abandoned.account_verified)
        self.assertTrue(self.imported.account_verified)
