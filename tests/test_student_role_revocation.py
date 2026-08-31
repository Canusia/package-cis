from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.student import Student
from cis.services.student_role import STUDENT
from cis.services.role_access import has_remaining_records, revoke_access


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class StudentRoleFixtureMixin:
    def build_fixture(self):
        self._saved_login_receivers = _disconnect_login_signal()

        self.student_group, _ = Group.objects.get_or_create(name='student')

        # user_a keeps a Student record throughout (still an active student).
        self.user_a = CustomUser.objects.create_user(
            username='studentrevoke_a', email='studentrevoke_a@example.com',
            password='x')
        self.student_a = Student.objects.create(user=self.user_a)

        # user_b's Student record is deleted within each test as needed.
        self.user_b = CustomUser.objects.create_user(
            username='studentrevoke_b', email='studentrevoke_b@example.com',
            password='x')
        self.student_b = Student.objects.create(user=self.user_b)

        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.ce_user = CustomUser.objects.create_superuser(
            username='studentrevoke_ce', email='studentrevoke_ce@example.com',
            password='x')
        self.ce_user.groups.add(ce_group)
        self.client.force_login(self.ce_user)

    def tear_down_fixture(self):
        _reconnect_login_signal(self._saved_login_receivers)


class StudentRoleServiceTests(StudentRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.user_a.groups.add(self.student_group)
        self.user_b.groups.add(self.student_group)

    def tearDown(self):
        self.tear_down_fixture()

    def test_has_remaining_records_is_true_while_a_record_exists(self):
        self.assertTrue(has_remaining_records(STUDENT, self.user_a))

    def test_revoke_refuses_while_a_record_exists(self):
        self.assertFalse(revoke_access(STUDENT, self.user_a))
        self.user_a.refresh_from_db()
        self.assertIn('student', self.user_a.get_roles())

    def test_revoke_drops_the_group_once_the_record_is_gone(self):
        Student.delete_record(self.student_b)

        self.assertTrue(revoke_access(STUDENT, self.user_b))
        self.user_b.refresh_from_db()
        self.assertNotIn('student', self.user_b.get_roles())

    def test_revoke_never_deletes_the_account(self):
        Student.delete_record(self.student_b)

        revoke_access(STUDENT, self.user_b)
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())

    def test_revoke_leaves_other_roles_alone(self):
        instructor_group, _ = Group.objects.get_or_create(name='instructor')
        self.user_b.groups.add(instructor_group)
        Student.delete_record(self.student_b)

        revoke_access(STUDENT, self.user_b)
        self.user_b.refresh_from_db()
        self.assertIn('instructor', self.user_b.get_roles())


class DeleteRecordKeepsTheAccountTests(StudentRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_delete_record_removes_only_the_student_record(self):
        Student.delete_record(self.student_b)

        self.assertFalse(Student.objects.filter(id=self.student_b.id).exists())
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())

    def test_delete_record_does_not_swallow_a_real_failure(self):
        """The old implementation wrapped user.delete() in a bare except, which
        is how accounts were left dangling. A failure deleting the record
        itself must raise, not silently half-succeed."""
        from unittest.mock import patch

        with patch.object(Student, 'delete', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                Student.delete_record(self.student_b)

        self.assertTrue(Student.objects.filter(id=self.student_b.id).exists())
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())

    def test_delete_record_returns_true_on_success(self):
        self.assertTrue(Student.delete_record(self.student_b))

    def test_partial_failure_does_not_destroy_other_related_records(self):
        """A failure partway through the cleanup must not destroy consents or
        FERPA records while leaving the student behind -- the whole cleanup
        plus the record delete must be one atomic unit.

        StudentCampusID is cleared early in Student.delete_record; ParentConsent
        is cleared later. Making the ParentConsent step raise simulates a
        PROTECT block downstream and proves the earlier StudentCampusID
        deletion is rolled back rather than left destroyed.
        """
        from unittest.mock import patch

        from cis.models.course import Campus
        from cis.models.student import StudentCampusID, ParentConsent

        campus = Campus.objects.create(name='Test Campus', code='TESTCAMPUS')
        campus_id = StudentCampusID.objects.create(
            student=self.student_b, campus=campus, user_id='12345')

        with patch.object(
            ParentConsent.objects, 'filter',
            side_effect=RuntimeError('protected')):
            with self.assertRaises(RuntimeError):
                Student.delete_record(self.student_b)

        self.assertTrue(
            StudentCampusID.objects.filter(pk=campus_id.pk).exists(),
            'the earlier deletion must be rolled back, not left destroyed')
        self.assertTrue(Student.objects.filter(id=self.student_b.id).exists())
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())


class RevokeRoleEndpointTests(StudentRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.user_b.groups.add(self.student_group)
        Student.delete_record(self.student_b)

    def tearDown(self):
        self.tear_down_fixture()

    def _url(self, user):
        return reverse('cis:revoke_student_role', args=[user.id])

    def test_post_revokes(self):
        resp = self.client.post(self._url(self.user_b))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'success')
        self.user_b.refresh_from_db()
        self.assertNotIn('student', self.user_b.get_roles())

    def test_get_is_refused(self):
        resp = self.client.get(self._url(self.user_b))
        self.assertEqual(resp.status_code, 405)
        self.user_b.refresh_from_db()
        self.assertIn('student', self.user_b.get_roles())

    def test_refuses_a_user_that_still_has_a_record(self):
        self.user_a.groups.add(self.student_group)
        resp = self.client.post(self._url(self.user_a))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'error')
        self.user_a.refresh_from_db()
        self.assertIn('student', self.user_a.get_roles())

    def test_message_names_retained_roles(self):
        instructor_group, _ = Group.objects.get_or_create(name='instructor')
        self.user_b.groups.add(instructor_group)
        resp = self.client.post(self._url(self.user_b))
        self.assertIn('instructor', resp.json()['message'])


class DeleteViewPayloadTests(StudentRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()
        self.user_b.groups.add(self.student_group)

    def tearDown(self):
        self.tear_down_fixture()

    def _delete(self, student):
        return self.client.post(reverse('cis:student_delete', args=[student.id]))

    def test_get_is_refused(self):
        resp = self.client.get(reverse('cis:student_delete', args=[self.student_b.id]))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Student.objects.filter(id=self.student_b.id).exists())

    def test_delete_offers_the_revoke_when_no_records_remain(self):
        resp = self._delete(self.student_b)
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload['status'], 'success')
        self.assertTrue(payload['student_role_revocable'])
        self.assertEqual(
            payload['revoke_url'],
            reverse('cis:revoke_student_role', args=[self.user_b.id]))

    def test_other_roles_are_reported(self):
        instructor_group, _ = Group.objects.get_or_create(name='instructor')
        self.user_b.groups.add(instructor_group)
        payload = self._delete(self.student_b).json()
        self.assertIn('instructor', payload['other_roles'])
        self.assertNotIn('student', payload['other_roles'])

    def test_account_survives_the_delete(self):
        self._delete(self.student_b)
        self.assertTrue(CustomUser.objects.filter(pk=self.user_b.pk).exists())
