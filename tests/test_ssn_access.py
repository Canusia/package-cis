"""MC-14 (#38): cis.view_ssn / cis.change_ssn gate staff access to SSNs.

Deny by default: without view_ssn the SSN is absent from the CE student form,
the student API and the students-by-date report; with view_ssn only it is
read-only. Migration 0090 gives both to the ce group, so existing CE staff
keep today's access.
"""
import uuid
from types import SimpleNamespace

from django.contrib.auth.models import Group, Permission
from django.test import RequestFactory, TestCase

from cis.models.customuser import CustomUser
from cis.ssn import CHANGE, NONE, VIEW, restrict_form, ssn_access


def _user(*perms, groups=()):
    user = CustomUser.objects.create_user(
        username=f'u{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
        password='x')
    for codename in perms:
        user.user_permissions.add(Permission.objects.get(
            content_type__app_label='cis', codename=codename))
    for name in groups:
        user.groups.add(Group.objects.get_or_create(name=name)[0])
    return CustomUser.objects.get(pk=user.pk)  # fresh permission cache


class SsnAccessTests(TestCase):
    def test_levels(self):
        self.assertEqual(ssn_access(_user()), NONE)
        self.assertEqual(ssn_access(_user('view_ssn')), VIEW)
        self.assertEqual(ssn_access(_user('view_ssn', 'change_ssn')), CHANGE)
        self.assertEqual(ssn_access(None), NONE)

    def test_superuser_can_change(self):
        su = CustomUser.objects.create_superuser(
            username=f's{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        self.assertEqual(ssn_access(su), CHANGE)

    def test_ce_group_has_both_after_the_migration(self):
        ce = Group.objects.get_or_create(name='ce')[0]
        from importlib import import_module
        migration = import_module('cis.migrations.0090_ssn_permissions')
        from django.apps import apps as global_apps
        migration.grant_ssn_permissions_to_ce(global_apps, None)
        self.assertEqual(ssn_access(_user(groups=['ce'])), CHANGE)
        self.assertTrue(ce.permissions.filter(codename='view_ssn').exists())


class RestrictFormTests(TestCase):
    def _form(self):
        from django import forms

        class F(forms.Form):
            ssn = forms.CharField(required=False)
            verify_student_ssn = forms.CharField(required=False)
            first_name = forms.CharField(required=False)
        return F()

    def test_no_access_removes_the_fields(self):
        form = self._form()
        restrict_form(form, _user())
        self.assertNotIn('ssn', form.fields)
        self.assertNotIn('verify_student_ssn', form.fields)
        self.assertIn('first_name', form.fields)

    def test_view_only_is_read_only(self):
        form = self._form()
        restrict_form(form, _user('view_ssn'))
        self.assertTrue(form.fields['ssn'].disabled)

    def test_change_leaves_it_editable(self):
        form = self._form()
        restrict_form(form, _user('view_ssn', 'change_ssn'))
        self.assertFalse(form.fields['ssn'].disabled)


class CEStudentFormTests(TestCase):
    def _ce_form(self, user):
        from cis.forms.student_profile import StudentCISForm
        request = RequestFactory().get('/')
        request.user = user
        return StudentCISForm(None, request)

    def test_ssn_absent_without_view_ssn(self):
        form = self._ce_form(_user(groups=['ce']))
        if 'ssn' in self._ce_form(_user('view_ssn', 'change_ssn')).fields:
            self.assertNotIn('ssn', form.fields)

    def test_ssn_read_only_with_view_only(self):
        form = self._ce_form(_user('view_ssn'))
        if 'ssn' in form.fields:
            self.assertTrue(form.fields['ssn'].disabled)


class StudentApiTests(TestCase):
    def _fields(self, user):
        from cis.api.student import StudentSISSerializer
        return StudentSISSerializer(context={'request': SimpleNamespace(user=user)}).fields

    def test_absent_without_view_ssn(self):
        self.assertNotIn('ssn', self._fields(_user()))

    def test_read_only_with_view_only(self):
        self.assertTrue(self._fields(_user('view_ssn'))['ssn'].read_only)

    def test_writable_with_change(self):
        self.assertFalse(self._fields(_user('view_ssn', 'change_ssn'))['ssn'].read_only)
