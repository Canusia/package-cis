"""Tenant-supplied CE staff permission flags (#91): EXTRA_FLAGS in the
tenant's services/staff_permissions.py become Yes/No fields on the staff user
form, are stored on the account like the built-in two, and are checked with
has_staff_permission(). No tenant module, no extra fields."""
import uuid
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.forms.user import UserForm
from cis.models.course import Campus
from cis.services import staff_permissions

User = get_user_model()
FLAGS = [('manage_state_funds', 'Manage State Funds', 'May post state funds.')]


def _flags(flags):
    return mock.patch.object(
        staff_permissions, 'get_tenant_override',
        lambda m, a: flags if (m, a) == ('staff_permissions', 'EXTRA_FLAGS') else None)


class StaffPermissionFlagTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='ce')
        self.campus = Campus.objects.create(
            name=f'A-{uuid.uuid4().hex[:6]}',
            code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')

    def _data(self, **extra):
        return {
            'first_name': 'New', 'last_name': 'Staff',
            'email': f'{uuid.uuid4().hex[:6]}@example.com', 'uses_sso': 'Yes',
            'is_active': 'Yes', 'manage_settings': 'No',
            'manage_staff_accounts': 'No',
            'process_campus': [str(self.campus.id)],
            'default_campus': str(self.campus.id), **extra,
        }

    def test_no_extra_fields_by_default(self):
        with _flags(None):
            form = UserForm()
        self.assertNotIn('manage_state_funds', form.fields)
        self.assertEqual(form.extra_permission_flags, [])

    def test_extra_flag_follows_the_built_in_ones(self):
        with _flags(FLAGS):
            form = UserForm()
        names = list(form.fields)
        self.assertEqual(names[names.index('manage_staff_accounts') + 1],
                         'manage_state_funds')
        self.assertEqual(form.fields['manage_state_funds'].label, 'Manage State Funds')

    def test_add_and_update_store_the_flag(self):
        with _flags(FLAGS):
            form = UserForm(self._data(manage_state_funds='Yes'))
            self.assertTrue(form.is_valid(), form.errors)
            user = User.add_new_staff(form)
            self.assertTrue(user.has_staff_permission('manage_state_funds'))

            form = UserForm(self._data(email=user.email, manage_state_funds='No'),
                            record=user)
            self.assertTrue(form.is_valid(), form.errors)
            user.update(form)
        user.refresh_from_db()
        self.assertFalse(user.has_staff_permission('manage_state_funds'))

    def test_superuser_has_every_flag(self):
        admin = User(is_superuser=True)
        self.assertTrue(admin.has_staff_permission('anything'))


class ReservedFlagKeyTests(TestCase):
    def test_built_in_keys_are_refused(self):
        with _flags([('default_campus', 'Default', '')]):
            with self.assertRaises(ValueError):
                staff_permissions.extra_staff_permission_flags()
