"""cis.services.user_deletion -- hard-deleting a CE staff account.

Pinned here:

1. Every PROTECT/RESTRICT reverse relation to CustomUser installed in this
   tenant is classified in the registry. An unclassified one fails closed (it
   blocks deletes), and this test turns that into a CI failure instead of a
   surprise in production when a package adds a new user FK.

2. The strategies: authorship is reassigned to the acting superuser, live
   assignments are cleared, per-user rows are removed, and role records block.

3. Audit logs are not reassigned. ImpersonationLog rows cascade, but their
   content survives in the deletion LogEntry, which is attributed to the actor.

4. Atomicity: a blocked user raises and nothing changes.
"""
import json

from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from cis.models.customuser import CustomUser
from cis.models.note import StudentNote
from cis.models.teacher import Teacher
from cis.services import user_deletion
from cis.services.user_deletion import (
    BLOCK, DELETE, NULLIFY, REASSIGN, UserDeletionBlocked, delete_user,
    preflight, user_relations,
)

User = get_user_model()


class RegistryCoverageTests(TestCase):
    def test_every_fail_closed_relation_is_classified(self):
        unclassified = sorted(
            '.'.join(key) for key, _rel, strategy in user_relations()
            if strategy == 'unclassified'
        )
        self.assertEqual(
            unclassified, [],
            msg='Classify these in cis/services/user_deletion.py REGISTRY: '
                + ', '.join(unclassified))

    def test_registry_strategies_are_known(self):
        for key, strategy in user_deletion.REGISTRY.items():
            self.assertIn(strategy, (REASSIGN, NULLIFY, DELETE, BLOCK), msg=key)


class UserDeletionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ce, _ = Group.objects.get_or_create(name='ce')

        def make(username, **kwargs):
            user = User.objects.create_user(
                username=username, email=f'{username}@example.com',
                password='x', **kwargs)
            user.groups.add(ce)
            return user

        cls.admin = make('del_admin', is_superuser=True,
                         first_name='Ada', last_name='Admin')
        cls.target = make('del_target', first_name='Tess', last_name='Target')
        cls.teacher_staff = make('del_teacher', first_name='Theo', last_name='Teach')
        Teacher.objects.create(user=cls.teacher_staff, orientation_note='')

    def _note(self, author, text='hello'):
        return StudentNote.objects.create(
            note=text, createdby=author, createdon=timezone.now())

    # -- preflight ----------------------------------------------------------

    def test_user_with_only_notes_is_deletable_with_counts(self):
        self._note(self.target)
        self._note(self.target)

        plan = preflight(self.target)

        self.assertTrue(plan.deletable, msg=plan.blockers)
        effects = {e.label: (e.strategy, e.count) for e in plan.effects}
        self.assertEqual(effects['cis.StudentNote.createdby'], (REASSIGN, 2))

    def test_preflight_is_read_only(self):
        note = self._note(self.target)
        preflight(self.target)
        note.refresh_from_db()
        self.assertEqual(note.createdby_id, self.target.id)

    def test_role_record_blocks(self):
        plan = preflight(self.teacher_staff)
        self.assertFalse(plan.deletable)
        self.assertTrue(any('cis.Teacher.user' in b for b in plan.blockers),
                        msg=plan.blockers)

    def test_unclassified_protect_relation_blocks(self):
        self._note(self.target)
        registry = dict(user_deletion.REGISTRY)
        del registry[('cis.StudentNote', 'createdby')]
        with self._patched_registry(registry):
            plan = preflight(self.target)
        self.assertFalse(plan.deletable)
        self.assertTrue(any('unclassified' in b and 'cis.StudentNote.createdby' in b
                            for b in plan.blockers), msg=plan.blockers)

    def _patched_registry(self, registry):
        from unittest import mock
        return mock.patch.object(user_deletion, 'REGISTRY', registry)

    # -- delete_user --------------------------------------------------------

    def test_notes_are_reassigned_to_acting_user(self):
        note = self._note(self.target)

        delete_user(self.target, acting_user=self.admin)

        self.assertFalse(CustomUser.objects.filter(pk=self.target.pk).exists())
        note.refresh_from_db()
        self.assertEqual(note.createdby_id, self.admin.id)

    def test_alerts_are_removed(self):
        from alerts.models import Alert
        Alert.objects.create(recipient=self.target, alert_type='x', message='m')

        delete_user(self.target, acting_user=self.admin)

        self.assertEqual(Alert.objects.filter(message='m').count(), 0)

    def test_nullable_assignment_is_cleared(self):
        from support_ticket.models import TicketType
        ticket_type = TicketType.objects.create(
            name='Help', applies_to='x', notify_emails='', assigned_to=self.target)

        delete_user(self.target, acting_user=self.admin)

        ticket_type.refresh_from_db()
        self.assertIsNone(ticket_type.assigned_to_id)

    def test_impersonation_log_snapshotted_into_deletion_logentry(self):
        from impersonate.models import ImpersonationLog
        ImpersonationLog.objects.create(
            impersonator=self.target, impersonating=self.teacher_staff,
            session_key='abc', session_started_at=timezone.now())

        delete_user(self.target, acting_user=self.admin)

        self.assertFalse(ImpersonationLog.objects.filter(session_key='abc').exists())
        entry = LogEntry.objects.get(
            action_flag=DELETION, object_id=str(self.target.pk),
            content_type__model='customuser')
        self.assertEqual(entry.user_id, self.admin.id)
        payload = json.loads(entry.change_message)
        self.assertEqual(payload['deleted_user']['email'], self.target.email)
        self.assertEqual(payload['impersonation_log'][0]['impersonating'],
                         self.teacher_staff.email)

    def test_user_history_survives(self):
        target_pk = self.target.pk
        delete_user(self.target, acting_user=self.admin)
        self.assertTrue(CustomUser.history.filter(id=target_pk).exists())

    def test_blocked_user_raises_and_nothing_changes(self):
        note = self._note(self.teacher_staff)

        with self.assertRaises(UserDeletionBlocked):
            delete_user(self.teacher_staff, acting_user=self.admin)

        self.assertTrue(CustomUser.objects.filter(pk=self.teacher_staff.pk).exists())
        note.refresh_from_db()
        self.assertEqual(note.createdby_id, self.teacher_staff.id)
