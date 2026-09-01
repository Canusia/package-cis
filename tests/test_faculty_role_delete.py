"""Faculty coordinator delete capability.

FacultyCoordinator has no delete path today. This is new capability, built to
the same account-safe contract as cis.models.teacher.Teacher.delete_record and
cis.models.student.Student.delete_record: never delete the CustomUser, delete
the related rows the coordinator owns inside one transaction.atomic() before
deleting the record itself, and revoke the `faculty` group as a separate
explicit step via cis.services.role_access.revoke_access.

EWU has no test factories; fixtures use direct Model.objects.create() (see
cis/tests/test_faculty_coordinator_tabs.py).
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course
from cis.models.faculty import FacultyCoordinator, FacultyCourseCoordinator
from cis.models.note import FacultyCoordinatorNote
from cis.services.faculty_role import FACULTY
from cis.services.role_access import has_remaining_records, revoke_access

User = get_user_model()


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class FacultyRoleFixtureMixin:
    def build_fixture(self):
        self._saved_login_receivers = _disconnect_login_signal()

        self.faculty_group, _ = Group.objects.get_or_create(name='faculty')

        # coordinator_a keeps a FacultyCoordinator record throughout.
        self.user_a = User.objects.create_user(
            username='facrevoke_a', email='facrevoke_a@example.com',
            password='x')
        self.coord_a = FacultyCoordinator.objects.create(user=self.user_a)

        # coordinator_b's record is deleted within each test as needed.
        self.user_b = User.objects.create_user(
            username='facrevoke_b', email='facrevoke_b@example.com',
            password='x')
        self.coord_b = FacultyCoordinator.objects.create(user=self.user_b)

        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.ce_user = User.objects.create_superuser(
            username='facrevoke_ce', email='facrevoke_ce@example.com',
            password='x')
        self.ce_user.groups.add(ce_group)
        self.client.force_login(self.ce_user)

    def tear_down_fixture(self):
        _reconnect_login_signal(self._saved_login_receivers)

    def _make_course(self, name='COURSE FR'):
        cohort = Cohort.objects.create(name=f'Cohort {name}', designator=name[:6])
        return Course.objects.create(
            catalog_number='101', title='Intro', name=name,
            cohort=cohort, credit_hours=3)


class FacultyRoleServiceTests(FacultyRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_has_remaining_records_is_true_while_a_record_exists(self):
        self.assertTrue(has_remaining_records(FACULTY, self.user_a))

    def test_revoke_refuses_while_a_record_exists(self):
        self.assertFalse(revoke_access(FACULTY, self.user_a))
        self.user_a.refresh_from_db()
        self.assertIn('faculty', self.user_a.get_roles())

    def test_revoke_drops_the_group_once_the_record_is_gone(self):
        FacultyCoordinator.delete_record(self.coord_b)

        self.assertTrue(revoke_access(FACULTY, self.user_b))
        self.user_b.refresh_from_db()
        self.assertNotIn('faculty', self.user_b.get_roles())

    def test_revoke_never_deletes_the_account(self):
        FacultyCoordinator.delete_record(self.coord_b)

        revoke_access(FACULTY, self.user_b)
        self.assertTrue(User.objects.filter(pk=self.user_b.pk).exists())


class DeleteRecordKeepsTheAccountTests(FacultyRoleFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_delete_record_removes_only_the_faculty_coordinator_record(self):
        FacultyCoordinator.delete_record(self.coord_b)

        self.assertFalse(
            FacultyCoordinator.objects.filter(id=self.coord_b.id).exists())
        self.assertTrue(User.objects.filter(pk=self.user_b.pk).exists())

    def test_delete_record_returns_true_on_success(self):
        self.assertTrue(FacultyCoordinator.delete_record(self.coord_b))

    def test_delete_record_does_not_swallow_a_real_failure(self):
        """The bug this whole body of work exists to remove is a bare except
        around user.delete(). A failure deleting the record itself must
        raise, not silently half-succeed."""
        from unittest.mock import patch

        with patch.object(
            FacultyCoordinator, 'delete', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                FacultyCoordinator.delete_record(self.coord_b)

        self.assertTrue(
            FacultyCoordinator.objects.filter(id=self.coord_b.id).exists())
        self.assertTrue(User.objects.filter(pk=self.user_b.pk).exists())

    def test_partial_failure_does_not_destroy_other_related_records(self):
        """A failure partway through the cleanup must not destroy the
        coordinator's course-coordinator rows while leaving the note deletion
        (and the record) behind -- the whole cleanup plus the record delete
        must be one atomic unit.

        Unlike Student (StudentSupportingDocument is a real PROTECT FK the
        model's own delete_record does not clear) or HSAdministrator (roles
        reference the record with PROTECT and are deliberately left alone),
        FacultyCoordinator has exactly two models pointing at it and both are
        PROTECT (models/faculty.py:140, models/note.py:127) -- and both are
        cleared by delete_record itself, per the spec for this task. So there
        is no real, uncleared relation left to trip a genuine ProtectedError
        here; this test simulates the downstream failure via mock, the same
        idiom test_student_role_revocation.py uses for ParentConsent, to
        prove the atomicity contract independent of any one blocker."""
        from unittest.mock import patch

        course = self._make_course('ATOMIC')
        blocker = FacultyCourseCoordinator.objects.create(
            faculty_coordinator=self.coord_b, course=course, status='Active')

        with patch.object(
            FacultyCoordinatorNote.objects, 'filter',
            side_effect=RuntimeError('simulated downstream block')):
            with self.assertRaises(RuntimeError):
                FacultyCoordinator.delete_record(self.coord_b)

        self.assertTrue(
            FacultyCourseCoordinator.objects.filter(pk=blocker.pk).exists(),
            'the earlier deletion must be rolled back, not left destroyed')
        self.assertTrue(
            FacultyCoordinator.objects.filter(id=self.coord_b.id).exists())
        self.assertTrue(User.objects.filter(pk=self.user_b.pk).exists())

    def test_faculty_teacher_assignment_is_untouched_by_a_coordinator_delete(self):
        """FacultyTeacherAssignment keys on CustomUser (CASCADE), not
        FacultyCoordinator -- deleting the coordinator record must not
        cascade into it."""
        from cis.models.faculty import FacultyTeacherAssignment
        from cis.models.term import AcademicYear
        from cis.models.teacher import Teacher

        course = self._make_course('FTA')
        academic_year = AcademicYear.objects.create(name='AY FTA')
        teacher_user = User.objects.create_user(
            username='fta_teacher', email='fta_teacher@example.com',
            password='x')
        teacher = Teacher.objects.create(user=teacher_user)
        assignment = FacultyTeacherAssignment.objects.create(
            user=self.user_b, course=course, teacher=teacher,
            academic_year=academic_year)

        FacultyCoordinator.delete_record(self.coord_b)

        self.assertTrue(
            FacultyTeacherAssignment.objects.filter(pk=assignment.pk).exists())


class BulkDeleteRoleRevocationTests(FacultyRoleFixtureMixin, TestCase):
    """cis.views.faculty.do_bulk_action's 'delete' branch (the faculty coords
    index bulk action) must follow the same account-safe contract as every
    other role delete: never delete the account, revoke the role once no
    FacultyCoordinator record remains, and never destroy a blocked record's
    related rows."""

    def setUp(self):
        self.build_fixture()
        self.url = reverse('cis:faculty_bulk_actions')

    def tearDown(self):
        self.tear_down_fixture()

    def _delete(self, ids):
        return self.client.post(self.url, {
            'action': 'delete',
            'ids[]': [str(i) for i in ids],
        })

    def test_deletable_coordinator_is_deleted_and_role_revoked(self):
        resp = self._delete([self.coord_b.id])

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            FacultyCoordinator.objects.filter(id=self.coord_b.id).exists())
        self.user_b.refresh_from_db()
        self.assertNotIn('faculty', self.user_b.get_roles())
        self.assertTrue(User.objects.filter(pk=self.user_b.pk).exists())

    def test_coordinator_blocked_by_protect_child_is_skipped_and_survives(self):
        """FacultyCoordinator.delete_record itself clears both known PROTECT
        relations (FacultyCourseCoordinator, FacultyCoordinatorNote), so
        there is no real, uncleared relation left that can trip a genuine
        ProtectedError -- see the mocked delete_record test for why. This
        exercises the view's `except ProtectedError` skip-and-report branch
        the same way, via mock, since a real reproduction is not possible
        with this model's actual relation graph."""
        from unittest.mock import patch
        from django.db.models import ProtectedError

        with patch.object(
            FacultyCoordinator, 'delete_record',
            side_effect=ProtectedError('blocked', [])):
            resp = self._delete([self.coord_b.id])

        self.assertEqual(resp.status_code, 200)
        self.assertIn('left in place', resp.json()['message'])
        self.assertTrue(
            FacultyCoordinator.objects.filter(id=self.coord_b.id).exists())
        self.user_b.refresh_from_db()
        self.assertIn('faculty', self.user_b.get_roles())

    def test_account_always_survives(self):
        course = self._make_course('BULKSURVIVE')
        FacultyCourseCoordinator.objects.create(
            faculty_coordinator=self.coord_b, course=course, status='Active')

        self._delete([self.coord_a.id, self.coord_b.id])

        self.assertTrue(User.objects.filter(pk=self.user_a.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.user_b.pk).exists())

    def test_successful_delete_removes_both_children_and_revokes_the_role(self):
        """The central claim of FacultyCoordinator.delete_record is that it
        clears BOTH real children (FacultyCourseCoordinator,
        FacultyCoordinatorNote) and then the record itself. Every other test
        in this file either mocks the delete or never attaches both children
        to a record that is actually, successfully deleted -- so nothing
        proves the happy path end to end. Drop either cleanup line from
        delete_record and this is the test that catches it: the child row
        left behind would make record.delete() raise a real ProtectedError,
        which the view reports as 'left in place' rather than deleted, and
        this test's assertions on resp.json()['message'] and the row counts
        would fail.

        Runs through the bulk-action view (not just the model method) so the
        delete-then-revoke chain is proven together on a real record, per
        the coordinator's fix-round-1 request.
        """
        course = self._make_course('HAPPYPATH')
        course_coordinator = FacultyCourseCoordinator.objects.create(
            faculty_coordinator=self.coord_b, course=course, status='Active')
        note = FacultyCoordinatorNote.objects.create(
            faculty_coordinator=self.coord_b, note='keep me until deleted',
            createdby=self.ce_user)

        resp = self._delete([self.coord_b.id])

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn('Deleted 1', payload['message'])
        self.assertNotIn('left in place', payload['message'])
        self.assertNotIn('failed unexpectedly', payload['message'])

        self.assertFalse(
            FacultyCoordinator.objects.filter(id=self.coord_b.id).exists())
        self.assertFalse(
            FacultyCourseCoordinator.objects.filter(
                pk=course_coordinator.pk).exists())
        self.assertFalse(
            FacultyCoordinatorNote.objects.filter(pk=note.pk).exists())

        self.assertTrue(User.objects.filter(pk=self.user_b.pk).exists())
        self.user_b.refresh_from_db()
        self.assertNotIn('faculty', self.user_b.get_roles())

    def test_get_is_refused(self):
        resp = self.client.get(self.url, {
            'action': 'delete',
            'ids[]': [str(self.coord_b.id)],
        })
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(
            FacultyCoordinator.objects.filter(id=self.coord_b.id).exists())

    def test_unknown_action_is_a_400(self):
        resp = self.client.get(self.url, {'action': 'nope', 'ids[]': []})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_action_over_get_does_not_reach_a_mutation(self):
        resp = self.client.get(self.url, {
            'action': 'nope',
            'ids[]': [str(self.coord_b.id)],
        })
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(
            FacultyCoordinator.objects.filter(id=self.coord_b.id).exists())

    def test_malformed_id_is_skipped_not_500(self):
        resp = self._delete(['not-a-uuid', self.coord_b.id])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            FacultyCoordinator.objects.filter(id=self.coord_b.id).exists())


class BulkDeleteButtonWiringTests(FacultyRoleFixtureMixin, TestCase):
    """Which table's bulk_actions the 'delete' action is attached to on the
    rendered /ce/faculty_coordinators/ page.

    The endpoint-level tests above (BulkDeleteRoleRevocationTests) prove
    do_faculty_coordinator_bulk_delete is correct once it receives
    FacultyCoordinator ids. They never checked which table's Delete button
    actually sends those ids -- the button was previously wired to
    faculty_coords_table (CourseAdministrator rows, api /ce/api/course_administrator),
    so clicking it would send CourseAdministrator ids into an endpoint that
    expects FacultyCoordinator ids: both are UUIDs, so the id guard passes,
    the lookup matches nothing, and it silently reports zero deleted.
    """

    def setUp(self):
        self.build_fixture()

    def tearDown(self):
        self.tear_down_fixture()

    def test_delete_action_is_on_the_faculty_table(self):
        resp = self.client.get(reverse('cis:faculty_coordinators'))
        self.assertEqual(resp.status_code, 200)

        faculty_table = resp.context['faculty_table']
        self.assertEqual(
            faculty_table['bulk_actions'] and set(faculty_table['bulk_actions']),
            {'delete'},
        )

    def test_delete_action_is_not_on_the_course_administrator_table(self):
        resp = self.client.get(reverse('cis:faculty_coordinators'))
        self.assertEqual(resp.status_code, 200)

        faculty_coords_table = resp.context['faculty_coords_table']
        self.assertNotIn('delete', faculty_coords_table['bulk_actions'] or {})
        self.assertIn(
            'change_course_administrator_status',
            faculty_coords_table['bulk_actions'],
        )
