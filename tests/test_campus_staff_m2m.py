"""MC-16 (#40): staff campus assignments are rows, not only JSON.

CustomUser.process_campuses mirrors campus['process_campus'] on save, a
campus's staff are found with a join, and deleting a campus removes its id
from every user's list. campus_gate keeps its API and behaviour.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import transaction
from django.test import TestCase

from cis.campus_gate import can_process_campus, get_process_campus_ids
from cis.models.course import Campus
from cis.models.customuser import CustomUser


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


class StaffCampusRowsTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')
        self.user = CustomUser.objects.create_user(
            username=f'ce{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])

    def assign(self, *campuses, **extra):
        self.user.campus = {'process_campus': [str(c.id) for c in campuses], **extra}
        self.user.save()

    def test_rows_follow_the_json_list(self):
        self.assign(self.c1, self.c2)
        self.assertEqual(set(self.user.process_campuses.all()), {self.c1, self.c2})
        self.assign(self.c2)
        self.assertEqual(list(self.user.process_campuses.all()), [self.c2])

    def test_unknown_ids_are_ignored(self):
        self.user.campus = {'process_campus': ['not-a-uuid', str(uuid.uuid4()), str(self.c1.id)]}
        self.user.save()
        self.assertEqual(list(self.user.process_campuses.all()), [self.c1])

    def test_active_staff_at_campus_uses_the_rows(self):
        self.assign(self.c1)
        self.assertIn(self.user, CustomUser.active_staff_at_campus(self.c1.id))
        self.assertNotIn(self.user, CustomUser.active_staff_at_campus(self.c2.id))

    def test_campus_gate_is_unchanged(self):
        self.assign(self.c1)
        self.assertEqual(get_process_campus_ids(self.user), [str(self.c1.id)])
        self.assertTrue(can_process_campus(self.user, self.c1))
        self.assertFalse(can_process_campus(self.user, self.c2))

    def test_deleting_a_campus_leaves_no_dangling_id(self):
        self.assign(self.c1, self.c2, default_campus=str(self.c2.id))
        self.c2.delete()
        self.user.refresh_from_db()
        self.assertEqual(self.user.campus['process_campus'], [str(self.c1.id)])
        self.assertEqual(self.user.campus['default_campus'], '')
        self.assertEqual(list(self.user.process_campuses.all()), [self.c1])

    def test_last_login_save_does_not_touch_rows(self):
        self.assign(self.c1)
        CustomUser.objects.filter(pk=self.user.pk).update(campus={'process_campus': []})
        self.user.save(update_fields=['last_login'])
        self.assertEqual(list(self.user.process_campuses.all()), [self.c1])


class DirectEditGuardTests(TestCase):
    """v0.1.1a: the JSON is the only way to change a user's campuses."""

    def setUp(self):
        self.c1 = _campus('C1')
        self.user = CustomUser.objects.create_user(
            username=f'ce{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')

    def test_direct_edits_are_refused_from_both_sides(self):
        from cis.signals.staff_campus import DirectProcessCampusEdit
        for edit in (lambda: self.user.process_campuses.add(self.c1),
                     lambda: self.user.process_campuses.set([self.c1]),
                     lambda: self.user.process_campuses.clear(),
                     lambda: self.c1.staff_users.add(self.user),
                     lambda: self.c1.staff_users.remove(self.user)):
            with self.assertRaises(DirectProcessCampusEdit):
                with transaction.atomic():
                    edit()
        self.assertFalse(self.user.process_campuses.exists())

    def test_saving_the_json_still_syncs(self):
        self.user.campus = {'process_campus': [str(self.c1.id)]}
        self.user.save()
        self.assertEqual(list(self.user.process_campuses.all()), [self.c1])

    def test_deleting_the_user_or_campus_still_works(self):
        self.user.campus = {'process_campus': [str(self.c1.id)]}
        self.user.save()
        self.c1.delete()
        self.user.delete()
