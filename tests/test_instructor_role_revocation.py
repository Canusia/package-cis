from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.teacher import Teacher
from cis.services.instructor_role import INSTRUCTOR
from cis.services.role_access import has_remaining_records, revoke_access


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class InstructorRoleFixtureMixin:
    def build_fixture(self):
        self._saved_login_receivers = _disconnect_login_signal()

        self.instructor_group, _ = Group.objects.get_or_create(name='instructor')

        # user_a keeps a Teacher record throughout (still an active instructor).
        self.user_a = CustomUser.objects.create_user(
            username='instructorrevoke_a', email='instructorrevoke_a@example.com',
            password='x')
        self.teacher_a = Teacher.objects.create(user=self.user_a, status='active')

        # user_b's Teacher record is deleted within each test as needed.
        self.user_b = CustomUser.objects.create_user(
            username='instructorrevoke_b', email='instructorrevoke_b@example.com',
            password='x')
        self.teacher_b = Teacher.objects.create(user=self.user_b, status='active')

        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.ce_user = CustomUser.objects.create_superuser(
            username='instructorrevoke_ce', email='instructorrevoke_ce@example.com',
            password='x')
        self.ce_user.groups.add(ce_group)
        self.client.force_login(self.ce_user)

    def tear_down_fixture(self):
        _reconnect_login_signal(self._saved_login_receivers)


class InstructorRoleServiceTests(InstructorRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.user_a.groups.add(self.instructor_group)
        self.user_b.groups.add(self.instructor_group)

    def tearDown(self):
        self.tear_down_fixture()

    def test_has_remaining_records_is_true_while_a_record_exists(self):
        self.assertTrue(has_remaining_records(INSTRUCTOR, self.user_a))

    def test_revoke_refuses_while_a_record_exists(self):
        self.assertFalse(revoke_access(INSTRUCTOR, self.user_a))
        self.user_a.refresh_from_db()
        self.assertIn('instructor', self.user_a.get_roles())

    def test_revoke_drops_the_group_once_the_record_is_gone(self):
        Teacher.delete_record(self.teacher_b)

        self.assertTrue(revoke_access(INSTRUCTOR, self.user_b))
        self.user_b.refresh_from_db()
        self.assertNotIn('instructor', self.user_b.get_roles())

    def test_revoke_never_deletes_the_account(self):
        Teacher.delete_record(self.teacher_b)

        revoke_access(INSTRUCTOR, self.user_b)
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())

    def test_revoke_leaves_other_roles_alone(self):
        student_group, _ = Group.objects.get_or_create(name='student')
        self.user_b.groups.add(student_group)
        Teacher.delete_record(self.teacher_b)

        revoke_access(INSTRUCTOR, self.user_b)
        self.user_b.refresh_from_db()
        self.assertIn('student', self.user_b.get_roles())


class DeleteRecordKeepsTheAccountTests(InstructorRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_delete_record_removes_only_the_teacher_record(self):
        Teacher.delete_record(self.teacher_b)

        self.assertFalse(Teacher.objects.filter(id=self.teacher_b.id).exists())
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())

    def test_delete_record_does_not_swallow_a_real_failure(self):
        """The old implementation wrapped user.delete() in a bare except, which
        is how accounts were left dangling. A failure deleting the record
        itself must raise, not silently half-succeed."""
        from unittest.mock import patch

        with patch.object(Teacher, 'delete', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                Teacher.delete_record(self.teacher_b)

        self.assertTrue(Teacher.objects.filter(id=self.teacher_b.id).exists())
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())

    def test_delete_record_returns_true_on_success(self):
        self.assertTrue(Teacher.delete_record(self.teacher_b))

    def test_delete_record_still_refuses_when_student_registrations_exist(self):
        """Pre-existing guard: keep it working unchanged."""
        from unittest.mock import patch

        from cis.models.section import ClassSection, StudentRegistration

        with patch.object(
            StudentRegistration.objects, 'filter',
            return_value=type('Qs', (), {'exists': lambda self: True})()):
            with self.assertRaises(ValueError):
                Teacher.delete_record(self.teacher_b)

        self.assertTrue(Teacher.objects.filter(id=self.teacher_b.id).exists())


class RevokeRoleEndpointTests(InstructorRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.user_b.groups.add(self.instructor_group)
        Teacher.delete_record(self.teacher_b)

    def tearDown(self):
        self.tear_down_fixture()

    def _url(self, user):
        return reverse('cis:revoke_instructor_role', args=[user.id])

    def test_post_revokes(self):
        resp = self.client.post(self._url(self.user_b))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'success')
        self.user_b.refresh_from_db()
        self.assertNotIn('instructor', self.user_b.get_roles())

    def test_get_is_refused(self):
        resp = self.client.get(self._url(self.user_b))
        self.assertEqual(resp.status_code, 405)
        self.user_b.refresh_from_db()
        self.assertIn('instructor', self.user_b.get_roles())

    def test_refuses_a_user_that_still_has_a_record(self):
        self.user_a.groups.add(self.instructor_group)
        resp = self.client.post(self._url(self.user_a))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'error')
        self.user_a.refresh_from_db()
        self.assertIn('instructor', self.user_a.get_roles())

    def test_message_names_retained_roles(self):
        student_group, _ = Group.objects.get_or_create(name='student')
        self.user_b.groups.add(student_group)
        resp = self.client.post(self._url(self.user_b))
        self.assertIn('student', resp.json()['message'])


class DeleteViewPayloadTests(InstructorRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.user_b.groups.add(self.instructor_group)

    def tearDown(self):
        self.tear_down_fixture()

    def _delete(self, teacher):
        return self.client.post(reverse('cis:instructor_delete', args=[teacher.id]))

    def test_get_is_refused(self):
        resp = self.client.get(reverse('cis:instructor_delete', args=[self.teacher_b.id]))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Teacher.objects.filter(id=self.teacher_b.id).exists())

    def test_delete_offers_the_revoke_when_no_records_remain(self):
        resp = self._delete(self.teacher_b)
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(payload['instructor_role_revocable'])
        self.assertEqual(
            payload['revoke_url'],
            reverse('cis:revoke_instructor_role', args=[self.user_b.id]))

    def test_other_roles_are_reported(self):
        student_group, _ = Group.objects.get_or_create(name='student')
        self.user_b.groups.add(student_group)
        payload = self._delete(self.teacher_b).json()
        self.assertIn('student', payload['other_roles'])
        self.assertNotIn('instructor', payload['other_roles'])

    def test_account_survives_the_delete(self):
        self._delete(self.teacher_b)
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())
