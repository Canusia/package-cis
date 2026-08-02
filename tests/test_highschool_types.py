"""Tenant-configurable HighSchool School Types.

Covers the three things that could silently regress: the model's choices stay
a callable (so relabeling never writes a migration), display goes through
labels rather than raw codes, and the bulk action replaces the set on every
selected school.
"""
import json
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool, hs_type_choices


class HsTypeChoicesTests(TestCase):
    def test_choices_come_from_the_tenant_service(self):
        self.assertEqual(hs_type_choices(),
                         [('zone_a', 'Zone A'), ('zone_b', 'Zone B'),
                          ('zone_c', 'Zone C')])

    def test_field_keeps_the_callable_not_the_labels(self):
        """The whole point of the callable: deconstruct() must hand the
        migration writer a function, never the tenant's wording. A literal
        here would bake tenant labels into cis migrations, which are
        hand-copied between tenant repos."""
        field = HighSchool._meta.get_field('hs_type')
        _, _, _, kwargs = field.deconstruct()

        self.assertTrue(callable(kwargs['choices']))
        self.assertIs(kwargs['choices'], hs_type_choices)

    def test_relabeling_produces_no_migration(self):
        from django.db.migrations.autodetector import MigrationAutodetector
        from django.db.migrations.loader import MigrationLoader
        from django.db.migrations.questioner import NonInteractiveMigrationQuestioner
        from django.db.migrations.state import ProjectState

        def relabeled():
            return [('zone_a', 'Renamed Zone A'), ('zone_b', 'Zone B'),
                    ('zone_c', 'Zone C')]

        with patch('cis.models.highschool.hs_type_choices', relabeled):
            loader = MigrationLoader(None, ignore_no_migrations=True)
            autodetector = MigrationAutodetector(
                loader.project_state(),
                ProjectState.from_apps(__import__('django.apps', fromlist=['apps']).apps),
                NonInteractiveMigrationQuestioner(specified_apps=set(), dry_run=True),
            )
            changes = autodetector.changes(graph=loader.graph, trim_to_apps={'cis'})

        hs_type_ops = [
            op
            for migration in changes.get('cis', [])
            for op in migration.operations
            if getattr(op, 'name', None) == 'hs_type'
        ]
        self.assertEqual(hs_type_ops, [])


class HsTypeDisplayTests(TestCase):
    def test_labels_and_display(self):
        hs = HighSchool.objects.create(name='Test HS', code='TST01',
                                       hs_type=['zone_a', 'zone_c'])

        self.assertEqual(hs.hs_type_labels, ['Zone A', 'Zone C'])
        self.assertEqual(hs.hs_type_display, 'Zone A, Zone C')

    def test_empty_type_displays_as_blank(self):
        hs = HighSchool.objects.create(name='No Type HS', code='TST02')

        self.assertEqual(hs.hs_type_labels, [])
        self.assertEqual(hs.hs_type_display, '')

    def test_unknown_stored_code_degrades_to_the_code(self):
        hs = HighSchool.objects.create(name='Legacy HS', code='TST03')
        HighSchool.objects.filter(pk=hs.pk).update(hs_type='retired_zone')
        hs.refresh_from_db()

        self.assertEqual(hs.hs_type_display, 'retired_zone')


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR (force_login builds its own bare request, so
    a client REMOTE_ADDR default does not reach it). Same helper the other
    cis tab tests use."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class SetHsTypeBulkActionTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            email='ce@example.com', username='ce@example.com', password='pw')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        self.url = reverse('cis:highschool_bulk_actions')
        self.a = HighSchool.objects.create(name='A HS', code='AAA01')
        self.b = HighSchool.objects.create(name='B HS', code='BBB01',
                                           hs_type=['zone_c'])

    def tearDown(self):
        _reconnect_login_signal(self._saved)

    def _post(self, data):
        return self.client.post(self.url, data)

    def test_first_post_returns_the_modal(self):
        response = self._post({'action': 'set_hs_type',
                               'ids[]': [str(self.a.pk)]})

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload['outcome'], 'modal')
        self.assertIn('Zone A', payload['html'])
        self.assertIn('name="apply" value="1"', payload['html'])

    def test_applies_to_every_selected_school(self):
        self._post({'action': 'set_hs_type', 'apply': '1',
                    'ids[]': [str(self.a.pk), str(self.b.pk)],
                    'hs_type': ['zone_b']})

        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual(list(self.a.hs_type), ['zone_b'])
        self.assertEqual(list(self.b.hs_type), ['zone_b'])

    def test_replaces_rather_than_appends(self):
        """b starts as zone_c; setting zone_a must not leave zone_c behind."""
        self._post({'action': 'set_hs_type', 'apply': '1',
                    'ids[]': [str(self.b.pk)], 'hs_type': ['zone_a']})

        self.b.refresh_from_db()
        self.assertEqual(list(self.b.hs_type), ['zone_a'])

    def test_selecting_none_clears_the_type(self):
        self._post({'action': 'set_hs_type', 'apply': '1',
                    'ids[]': [str(self.b.pk)]})

        self.b.refresh_from_db()
        self.assertEqual(list(self.b.hs_type), [])

    def test_unknown_code_is_rejected_and_writes_nothing(self):
        response = self._post({'action': 'set_hs_type', 'apply': '1',
                               'ids[]': [str(self.b.pk)],
                               'hs_type': ['zone_x']})

        self.assertEqual(response.status_code, 400)
        self.b.refresh_from_db()
        self.assertEqual(list(self.b.hs_type), ['zone_c'])

    def test_no_selection_is_rejected(self):
        response = self._post({'action': 'set_hs_type'})

        self.assertEqual(response.status_code, 400)
