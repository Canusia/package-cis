import dataclasses
import json
from unittest import mock

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    HSAdministrator, HSAdministratorPosition, HSPosition,
)
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.services.relink_role_user import (
    HS_ADMIN_RELINK, INSTRUCTOR_RELINK, RelinkError, relink,
)


def _user(slug, **kwargs):
    return CustomUser.objects.create_user(
        username=slug, email=f'{slug}@example.com', password='x',
        first_name=slug.title(), last_name='Relink', **kwargs)


class RelinkFixtureMixin:
    def build_fixture(self):
        self.instructor_group, _ = Group.objects.get_or_create(name='instructor')
        self.hs_admin_group, _ = Group.objects.get_or_create(name='highschool_admin')
        self.student_group, _ = Group.objects.get_or_create(name='student')

        self.ce_user = CustomUser.objects.create_superuser(
            username='relink_ce', email='relink_ce@example.com', password='x')

        # The instructor's own (duplicate) account.
        self.old_teacher_user = _user('relink_old_teacher')
        self.old_teacher_user.groups.add(self.instructor_group)
        self.teacher = Teacher.objects.create(user=self.old_teacher_user, status='active')

        # The account the person really uses (an HS admin elsewhere).
        self.target = _user('relink_target')

        # An HS administrator with one active position.
        self.highschool = HighSchool.objects.create(name='Relink High')
        self.position, _ = HSPosition.objects.get_or_create(name='Relink Contact')
        self.old_admin_user = _user('relink_old_admin')
        self.old_admin_user.groups.add(self.hs_admin_group)
        self.hs_admin = HSAdministrator.objects.create(user=self.old_admin_user)
        HSAdministratorPosition.objects.create(
            hsadmin=self.hs_admin, highschool=self.highschool,
            position=self.position, status='Active')


class InstructorRelinkServiceTests(RelinkFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def test_moves_the_record_to_the_target(self):
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.user_id, self.target.pk)

    def test_grants_the_instructor_group_to_the_target(self):
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.assertIn('instructor', self.target.get_roles())

    def test_revokes_the_group_from_the_old_account(self):
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.old_teacher_user.refresh_from_db()
        self.assertNotIn('instructor', self.old_teacher_user.get_roles())

    def test_deactivates_an_old_account_left_with_no_role(self):
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.old_teacher_user.refresh_from_db()
        self.assertFalse(self.old_teacher_user.is_active)

    def test_keeps_an_old_account_that_has_another_role_active(self):
        self.old_teacher_user.groups.add(self.student_group)
        Student.objects.create(user=self.old_teacher_user)
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.old_teacher_user.refresh_from_db()
        self.assertTrue(self.old_teacher_user.is_active)
        self.assertIn('student', self.old_teacher_user.get_roles())

    def test_keeps_an_old_staff_account_active(self):
        self.old_teacher_user.is_staff = True
        self.old_teacher_user.save()
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.old_teacher_user.refresh_from_db()
        self.assertTrue(self.old_teacher_user.is_active)

    def test_never_deletes_the_old_account(self):
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.assertTrue(CustomUser.objects.filter(pk=self.old_teacher_user.pk).exists())

    def test_reactivates_an_inactive_target(self):
        self.target.is_active = False
        self.target.save()
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_leaves_the_target_profile_alone(self):
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, 'Relink_Target')
        self.assertEqual(self.target.email, 'relink_target@example.com')

    def test_writes_an_audit_log_entry(self):
        relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        entry = LogEntry.objects.get(object_id=str(self.teacher.pk))
        self.assertEqual(entry.user, self.ce_user)
        detail = json.loads(entry.change_message)['relinked_user']
        self.assertEqual(detail['from']['id'], self.old_teacher_user.pk)
        self.assertEqual(detail['to']['id'], self.target.pk)
        self.assertTrue(detail['old_user_deactivated'])

    def test_refuses_a_missing_target(self):
        with self.assertRaises(RelinkError):
            relink(INSTRUCTOR_RELINK, self.teacher, None, self.ce_user)

    def test_refuses_the_current_account(self):
        with self.assertRaises(RelinkError):
            relink(INSTRUCTOR_RELINK, self.teacher, self.old_teacher_user, self.ce_user)

    def test_refuses_a_target_that_already_has_a_teacher_record(self):
        Teacher.objects.create(user=self.target)
        with self.assertRaises(RelinkError):
            relink(INSTRUCTOR_RELINK, self.teacher, self.target, self.ce_user)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.user_id, self.old_teacher_user.pk)

    def test_rolls_back_everything_when_a_step_fails(self):
        failing = dataclasses.replace(
            INSTRUCTOR_RELINK, revoke=mock.Mock(side_effect=RuntimeError('boom')))
        with self.assertRaises(RuntimeError):
            relink(failing, self.teacher, self.target, self.ce_user)

        self.teacher.refresh_from_db()
        self.target.refresh_from_db()
        self.old_teacher_user.refresh_from_db()
        self.assertEqual(self.teacher.user_id, self.old_teacher_user.pk)
        self.assertNotIn('instructor', self.target.get_roles())
        self.assertIn('instructor', self.old_teacher_user.get_roles())
        self.assertTrue(self.old_teacher_user.is_active)
        self.assertFalse(LogEntry.objects.filter(object_id=str(self.teacher.pk)).exists())


class HSAdminRelinkServiceTests(RelinkFixtureMixin, TestCase):
    def setUp(self):
        self.build_fixture()

    def test_moves_the_record_and_its_positions(self):
        relink(HS_ADMIN_RELINK, self.hs_admin, self.target, self.ce_user)
        self.hs_admin.refresh_from_db()
        self.assertEqual(self.hs_admin.user_id, self.target.pk)
        self.assertTrue(HSAdministratorPosition.objects.filter(
            hsadmin__user=self.target, highschool=self.highschool).exists())

    def test_grants_the_group_when_a_position_is_active(self):
        relink(HS_ADMIN_RELINK, self.hs_admin, self.target, self.ce_user)
        self.assertIn('highschool_admin', self.target.get_roles())

    def test_withholds_the_group_when_no_position_is_active(self):
        HSAdministratorPosition.objects.filter(hsadmin=self.hs_admin).update(status='Inactive')
        relink(HS_ADMIN_RELINK, self.hs_admin, self.target, self.ce_user)
        self.assertNotIn('highschool_admin', self.target.get_roles())

    def test_revokes_and_deactivates_the_old_account(self):
        relink(HS_ADMIN_RELINK, self.hs_admin, self.target, self.ce_user)
        self.old_admin_user.refresh_from_db()
        self.assertNotIn('highschool_admin', self.old_admin_user.get_roles())
        self.assertFalse(self.old_admin_user.is_active)

    def test_does_not_delete_the_moved_record(self):
        """revoke_hs_admin_access deletes the old user's HSAdministrator
        shells; the moved record must no longer count as one of them."""
        relink(HS_ADMIN_RELINK, self.hs_admin, self.target, self.ce_user)
        self.assertTrue(HSAdministrator.objects.filter(pk=self.hs_admin.pk).exists())

    def test_teacher_target_keeps_instructor_role(self):
        """The motivating case: the HS admin is also an instructor on the target."""
        self.target.groups.add(self.instructor_group)
        Teacher.objects.create(user=self.target)
        relink(HS_ADMIN_RELINK, self.hs_admin, self.target, self.ce_user)
        self.assertEqual(
            set(self.target.get_roles()), {'instructor', 'highschool_admin'})

    def test_refuses_a_target_that_already_has_an_hs_admin_record(self):
        HSAdministrator.objects.create(user=self.target)
        with self.assertRaises(RelinkError):
            relink(HS_ADMIN_RELINK, self.hs_admin, self.target, self.ce_user)


class RelinkViewTests(RelinkFixtureMixin, TestCase):
    def setUp(self):
        self._receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        self.build_fixture()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.ce_user.groups.add(ce_group)
        self.client.force_login(self.ce_user)
        self.url = reverse('cis:instructor_relink_user', args=[self.teacher.pk])

    def tearDown(self):
        user_logged_in.receivers = self._receivers

    def test_get_shows_the_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Find account')

    def test_lookup_previews_without_changing_anything(self):
        response = self.client.post(self.url, {'email': 'RELINK_TARGET@example.com'})
        self.assertContains(response, 'Link to this account')
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.user_id, self.old_teacher_user.pk)

    def test_unknown_email_shows_an_error(self):
        response = self.client.post(self.url, {'email': 'nobody@example.com'})
        self.assertContains(response, 'No account exists with that email address.')

    def test_confirm_relinks_and_redirects_to_the_detail_page(self):
        response = self.client.post(
            self.url, {'email': 'relink_target@example.com', 'confirm': '1'})
        self.assertRedirects(
            response, reverse('cis:instructor', args=[self.teacher.pk]),
            fetch_redirect_response=False)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.user_id, self.target.pk)

    def test_hs_admin_confirm_relinks(self):
        url = reverse('cis:hs_admin_relink_user', args=[self.hs_admin.pk])
        response = self.client.post(
            url, {'email': 'relink_target@example.com', 'confirm': '1'})
        self.assertEqual(response.status_code, 302)
        self.hs_admin.refresh_from_db()
        self.assertEqual(self.hs_admin.user_id, self.target.pk)

    def test_non_ce_user_is_turned_away(self):
        self.client.force_login(self.target)
        response = self.client.post(
            self.url, {'email': 'relink_target@example.com', 'confirm': '1'})
        self.assertEqual(response.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.user_id, self.old_teacher_user.pk)

    def test_detail_pages_link_to_the_action(self):
        self.assertContains(
            self.client.get(reverse('cis:instructor', args=[self.teacher.pk])),
            self.url)
        self.assertContains(
            self.client.get(reverse('cis:hs_admin', args=[self.hs_admin.pk])),
            reverse('cis:hs_admin_relink_user', args=[self.hs_admin.pk]))
