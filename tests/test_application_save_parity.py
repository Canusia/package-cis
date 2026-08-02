"""save() parity between the two application form paths.

`StudentProfileForm.save()` does three things beyond routing fields to their
storage target, and `SpecDrivenApplicationForm.save()` did none of them:

    * hash the password onto the user
    * persist notification preferences
    * stamp `profile_dirty_at` on a self-edit

All three are engine concerns, not tenant ones — `password_pair` is a cis field
type, `Student.notifications` is a cis model field, and the dirty flag is
driven by the cis `student_profile` setting. Until they are shared, arming any
tenant spec would log a student in with an unusable password, since
`complete_signup` calls `form.save(student)` and then `auth.login()` without
touching the password itself.

Found while sccc authored the first real spec (Canusia/sccc#17).
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from cis.forms.application_form import SpecDrivenApplicationForm
from cis.models.student import Student

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class SaveParityTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        self.email = f'app-{_sfx()}@example.com'
        self.user = User.objects.create_user(
            username=self.email, email=self.email, password='initial-password')
        self.student = Student.objects.create(user=self.user)

    def _save(self, spec, data, request=None):
        form = SpecDrivenApplicationForm(spec=spec, rules=[], student=self.student,
                                         request=request, data=data)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.refresh_from_db()
        self.student.refresh_from_db()
        return form

    # --- password -------------------------------------------------------

    PASSWORD_SPEC = [
        {'name': 'password', 'type': 'password_pair', 'label': 'Password',
         'target': 'skip'},
    ]

    def test_password_is_hashed_onto_the_user(self):
        self._save(self.PASSWORD_SPEC,
                   {'password': 'Corr3ct-Horse!', 'confirm_password': 'Corr3ct-Horse!'})
        self.assertTrue(self.user.check_password('Corr3ct-Horse!'))

    def test_password_is_never_stored_in_the_clear(self):
        self._save(self.PASSWORD_SPEC,
                   {'password': 'Corr3ct-Horse!', 'confirm_password': 'Corr3ct-Horse!'})
        self.assertNotIn('Corr3ct-Horse!', self.user.password)
        self.assertNotIn('Corr3ct-Horse!', str(self.student.meta or {}))

    def test_a_blank_password_leaves_the_existing_one_alone(self):
        """An edit form that does not ask for a password must not wipe it."""
        spec = [{'name': 'first_name', 'type': 'text', 'label': 'First',
                 'target': 'user'}]
        self._save(spec, {'first_name': 'Ada'})
        self.assertTrue(self.user.check_password('initial-password'))

    # --- notifications --------------------------------------------------

    def test_notifications_target_routes_into_student_notifications(self):
        spec = [
            {'name': 'cell_phone_opt_in', 'type': 'agreement',
             'label': 'Text me', 'target': 'notifications', 'required': False},
        ]
        self._save(spec, {'cell_phone_opt_in': 'on'})
        self.assertEqual(self.student.notifications.get('cell_phone_opt_in'), True)

    def test_notifications_target_preserves_other_keys(self):
        self.student.notifications = {'existing': 'keep me'}
        self.student.save()
        spec = [
            {'name': 'cell_phone_opt_in', 'type': 'agreement',
             'label': 'Text me', 'target': 'notifications', 'required': False},
        ]
        self._save(spec, {'cell_phone_opt_in': 'on'})
        self.assertEqual(self.student.notifications.get('existing'), 'keep me')

    def test_notifications_target_populates_initial(self):
        self.student.notifications = {'cell_phone_opt_in': True}
        self.student.save()
        spec = [
            {'name': 'cell_phone_opt_in', 'type': 'agreement',
             'label': 'Text me', 'target': 'notifications', 'required': False},
        ]
        form = SpecDrivenApplicationForm(spec=spec, rules=[], student=self.student)
        self.assertEqual(form.initial['cell_phone_opt_in'], True)

    # --- profile_dirty_at -----------------------------------------------

    SPEC = [{'name': 'first_name', 'type': 'text', 'label': 'First',
             'target': 'user'}]

    def _request_from(self, user):
        request = RequestFactory().post('/')
        request.user = user
        return request

    def test_self_edit_that_changes_a_field_stamps_profile_dirty_at(self):
        self.user.first_name = 'Ada'
        self.user.save()
        self._save(self.SPEC, {'first_name': 'Grace'},
                   request=self._request_from(self.user))
        self.assertIsNotNone(self.student.profile_dirty_at)

    def test_self_edit_that_changes_nothing_does_not_stamp(self):
        self.user.first_name = 'Ada'
        self.user.save()
        self._save(self.SPEC, {'first_name': 'Ada'},
                   request=self._request_from(self.user))
        self.assertIsNone(self.student.profile_dirty_at)

    def test_a_staff_edit_does_not_stamp(self):
        """The flag exists so CE staff can review *student* changes; their own
        edits are not something to review."""
        staff_email = f'ce-{_sfx()}@example.com'
        staff = User.objects.create_user(username=staff_email, email=staff_email,
                                         password='x')
        self.user.first_name = 'Ada'
        self.user.save()
        self._save(self.SPEC, {'first_name': 'Grace'},
                   request=self._request_from(staff))
        self.assertIsNone(self.student.profile_dirty_at)

    def test_no_request_does_not_stamp(self):
        """An unauthenticated signup has no request user to compare against."""
        self._save(self.SPEC, {'first_name': 'Grace'})
        self.assertIsNone(self.student.profile_dirty_at)
