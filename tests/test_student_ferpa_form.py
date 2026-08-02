"""StudentFerpaForm validation: a student must be able to AUTHORIZE, not only
decline.

`releases` draws its choices from StudentFerpa.RELEASES, which is entirely
commented out, and the student template never renders the field — so forcing
it required on the authorize path made every authorize POST fail with
"This field is required." (all 15 staging rows are release_status='decline').
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.http import QueryDict
from django.test import TestCase

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.forms.student import StudentFerpaForm
from cis.models.student import Student, StudentFerpa

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class StudentFerpaFormTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        Group.objects.get_or_create(name='student')
        u = User.objects.create_user(
            username=f'stu_{_sfx()}', email=f'stu_{_sfx()}@x.com', password='x')
        self.student = Student.objects.create(user=u, account_verified=True)

    def _post(self, **overrides):
        """A POST shaped like the FERPA form template: two contact rows, the second
        blank, and no `releases` input (the template never renders one)."""
        data = QueryDict(mutable=True)
        data.update({
            'student': str(self.student.id),
            'release_status': 'authorize',
            'student_signature': 'Jane Q Student',
            'other_releases': '',
        })
        data.setlist('permissions[name]', ['Pat Guardian', ''])
        data.setlist('permissions[relationship]', ['Mother', ''])
        data.setlist('permissions[passphrase]', ['hunter2', ''])
        data.setlist('permissions[academic_information_0]', ['on'])
        for key, value in overrides.items():
            data.setlist(key, value if isinstance(value, list) else [value])
        return data

    def test_authorize_post_validates(self):
        form = StudentFerpaForm(self.student, data=self._post())
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_authorize_post_saves_permissions_and_signature(self):
        form = StudentFerpaForm(self.student, data=self._post())
        self.assertTrue(form.is_valid(), form.errors.as_json())
        ferpa = form.save()

        ferpa.refresh_from_db()
        self.assertEqual(ferpa.permissions_granted['release_status'], 'authorize')
        self.assertEqual(ferpa.student_signature, 'Jane Q Student')
        permissions = ferpa.permissions_granted['permissions']
        self.assertEqual(permissions['names'], ['Pat Guardian', ''])
        self.assertEqual(permissions['relationships'], ['Mother', ''])
        self.assertEqual(permissions['academic_information_0'], ['on'])
        self.assertEqual(ferpa.permissions_granted['releases'], [])

    def test_authorize_still_requires_a_signature(self):
        form = StudentFerpaForm(
            self.student, data=self._post(student_signature=''))
        self.assertFalse(form.is_valid())

    def test_authorize_still_requires_a_contact(self):
        form = StudentFerpaForm(
            self.student, data=self._post(**{'permissions[name]': ['', '']}))
        self.assertFalse(form.is_valid())

    def test_authorize_contact_requires_academic_or_financial_permission(self):
        form = StudentFerpaForm(
            self.student,
            data=self._post(**{'permissions[academic_information_0]': []}))
        self.assertFalse(form.is_valid())

    def test_decline_post_validates_and_saves(self):
        data = self._post(release_status='decline', student_signature='')
        data.setlist('permissions[name]', ['', ''])
        data.setlist('permissions[relationship]', ['', ''])
        data.setlist('permissions[passphrase]', ['', ''])
        data.setlist('permissions[academic_information_0]', [])

        form = StudentFerpaForm(self.student, data=data)
        self.assertTrue(form.is_valid(), form.errors.as_json())
        ferpa = form.save()

        ferpa.refresh_from_db()
        self.assertEqual(ferpa.permissions_granted['release_status'], 'decline')
        self.assertTrue(StudentFerpa.has_signed(self.student))
