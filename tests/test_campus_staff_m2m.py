"""Staff campus assignments: CustomUser.process_campuses is the only source (#59).

Access checks read the M2M; it is changed with set_process_campuses() or any
M2M edit, from either side. campus['process_campus'] is a read-only mirror
for one release: rewritten after every change, and a save that changes it
raises. Deleting a campus leaves no dangling id. (MC-16 #40 introduced the
M2M as a copy of the JSON; #59 turned the direction round.)
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.campus_gate import can_process_campus, get_process_campus_ids
from cis.models.course import Campus
from cis.models.customuser import CustomUser
from cis.signals.staff_campus import ProcessCampusJSONReadOnly


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


class StaffCampusTests(TestCase):
    def setUp(self):
        self.c1 = _campus('A')
        self.c2 = _campus('B')
        self.user = CustomUser.objects.create_user(
            username=f'ce{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])

    def fresh(self):
        return CustomUser.objects.get(pk=self.user.pk)

    def test_set_process_campuses_drives_the_gate(self):
        self.user.set_process_campuses([self.c1])
        user = self.fresh()
        self.assertEqual(get_process_campus_ids(user), [str(self.c1.id)])
        self.assertTrue(can_process_campus(user, self.c1))
        self.assertFalse(can_process_campus(user, self.c2))

    def test_unknown_ids_are_ignored(self):
        self.user.set_process_campuses(['not-a-uuid', str(uuid.uuid4()), str(self.c1.id)])
        self.assertEqual(list(self.user.process_campuses.all()), [self.c1])

    def test_json_mirrors_every_change_from_either_side(self):
        self.user.set_process_campuses([self.c2, self.c1])
        self.assertEqual(self.fresh().campus['process_campus'], [str(self.c1.id), str(self.c2.id)])
        self.assertEqual(self.user.campus['process_campus'], [str(self.c1.id), str(self.c2.id)])
        self.c1.staff_users.remove(self.user)
        self.assertEqual(self.fresh().campus['process_campus'], [str(self.c2.id)])
        self.c1.staff_users.add(self.user)
        self.c2.staff_users.clear()
        self.assertEqual(self.fresh().campus['process_campus'], [str(self.c1.id)])

    def test_writing_the_json_is_refused(self):
        self.user.set_process_campuses([self.c1])
        user = self.fresh()
        user.campus = dict(user.campus, process_campus=[str(self.c2.id)])
        with self.assertRaises(ProcessCampusJSONReadOnly):
            user.save()
        self.assertEqual(get_process_campus_ids(self.fresh()), [str(self.c1.id)])

    def test_new_user_with_json_list_is_refused(self):
        with self.assertRaises(ProcessCampusJSONReadOnly):
            CustomUser.objects.create_user(
                username=f'n{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
                password='x', campus={'process_campus': [str(self.c1.id)]})

    def test_stale_copy_does_not_clobber_the_list(self):
        stale = self.fresh()
        self.c1.staff_users.add(self.user)
        stale.first_name = 'Renamed'
        stale.campus = dict(stale.campus or {}, manage_settings='Yes')
        stale.save()
        user = self.fresh()
        self.assertEqual(user.campus['process_campus'], [str(self.c1.id)])
        self.assertEqual(user.campus['manage_settings'], 'Yes')
        self.assertEqual(get_process_campus_ids(user), [str(self.c1.id)])

    def test_other_keys_still_save(self):
        self.user.set_process_campuses([self.c1])
        user = self.fresh()
        user.campus['default_campus'] = str(self.c1.id)
        user.save()
        self.assertEqual(self.fresh().campus['default_campus'], str(self.c1.id))

    def test_active_staff_at_campus(self):
        self.user.set_process_campuses([self.c1])
        self.assertIn(self.user, CustomUser.active_staff_at_campus(self.c1.id))
        self.assertNotIn(self.user, CustomUser.active_staff_at_campus(self.c2.id))

    def test_deleting_a_campus_leaves_no_dangling_id(self):
        self.user.set_process_campuses([self.c1, self.c2])
        user = self.fresh()
        user.campus['default_campus'] = str(self.c2.id)
        user.save()
        self.c2.delete()
        user = self.fresh()
        self.assertEqual(user.campus['process_campus'], [str(self.c1.id)])
        self.assertEqual(user.campus['default_campus'], '')
        self.assertEqual(get_process_campus_ids(user), [str(self.c1.id)])

    def test_login_save_skips_the_check(self):
        self.user.set_process_campuses([self.c1])
        self.user.save(update_fields=['last_login'])
        self.assertEqual(list(self.user.process_campuses.all()), [self.c1])


class StaffFormTests(TestCase):
    """The /ce/user/<id> form writes the M2M."""

    def test_update_sets_campuses(self):
        from types import SimpleNamespace
        c1 = _campus('A')
        user = CustomUser.objects.create_user(
            username=f'ce{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        form = SimpleNamespace(cleaned_data={
            'first_name': 'F', 'last_name': 'L', 'email': user.email,
            'username': user.username, 'is_active': 'Yes', 'password': '',
            'process_campus': [str(c1.id)], 'default_campus': str(c1.id),
            'manage_settings': 'No', 'manage_staff_accounts': 'No'})
        user.update(form)
        self.assertEqual(list(user.process_campuses.all()), [c1])
        self.assertEqual(CustomUser.objects.get(pk=user.pk).campus['process_campus'], [str(c1.id)])
