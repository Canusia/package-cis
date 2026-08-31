from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models import CustomUser
from cis.models.teacher import Teacher
from cis.services.role_access import (
    RoleAccessPolicy, dangling_users, has_remaining_records, revoke_access,
)


INSTRUCTOR = RoleAccessPolicy(
    group_name='instructor',
    record_model_path='cis.Teacher',
)


class RoleAccessPolicyTests(TestCase):
    def setUp(self):
        self.group, _ = Group.objects.get_or_create(name='instructor')
        self.other, _ = Group.objects.get_or_create(name='student')

        self.with_record = CustomUser.objects.create_user(
            username='has_rec', email='has_rec@example.com', password='x',
            first_name='Hana', last_name='Record')
        self.with_record.groups.add(self.group)
        self.teacher = Teacher.objects.create(user=self.with_record)

        self.orphan = CustomUser.objects.create_user(
            username='orphan', email='orphan@example.com', password='x',
            first_name='Ora', last_name='Phan')
        self.orphan.groups.add(self.group)

        self.outsider = CustomUser.objects.create_user(
            username='outsider', email='outsider@example.com', password='x')
        self.outsider.groups.add(self.other)

    def test_has_remaining_records_is_true_with_a_record(self):
        self.assertTrue(has_remaining_records(INSTRUCTOR, self.with_record))

    def test_has_remaining_records_is_false_without_one(self):
        self.assertFalse(has_remaining_records(INSTRUCTOR, self.orphan))

    def test_revoke_refuses_while_a_record_exists(self):
        self.assertFalse(revoke_access(INSTRUCTOR, self.with_record))
        self.with_record.refresh_from_db()
        self.assertIn('instructor', self.with_record.get_roles())

    def test_revoke_drops_the_group_when_no_record_remains(self):
        self.assertTrue(revoke_access(INSTRUCTOR, self.orphan))
        self.orphan.refresh_from_db()
        self.assertNotIn('instructor', self.orphan.get_roles())

    def test_revoke_never_deletes_the_account(self):
        revoke_access(INSTRUCTOR, self.orphan)
        self.assertTrue(CustomUser.objects.filter(pk=self.orphan.pk).exists())

    def test_revoke_leaves_other_roles_alone(self):
        self.orphan.groups.add(self.other)
        revoke_access(INSTRUCTOR, self.orphan)
        self.orphan.refresh_from_db()
        self.assertIn('student', self.orphan.get_roles())

    def test_revoke_tolerates_a_missing_group(self):
        """A tenant that has not run init_groups must not 500."""
        Group.objects.filter(name='instructor').delete()
        self.assertTrue(revoke_access(INSTRUCTOR, self.orphan))

    def test_dangling_users_lists_only_group_members_without_a_record(self):
        listed = set(dangling_users(INSTRUCTOR).values_list('pk', flat=True))
        self.assertEqual(listed, {self.orphan.pk})

    def test_dangling_users_has_no_duplicate_rows(self):
        """A user in the group twice over (m2m join) must appear once."""
        self.orphan.groups.add(self.other)
        self.assertEqual(dangling_users(INSTRUCTOR).count(), 1)
