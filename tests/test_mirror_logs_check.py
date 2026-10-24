"""System check cis.W013 (package-cis#85): ethos installed after migration
0056 ran leaves StudentRegistration.mirror_logs without its table."""
from unittest import mock

from django.db import OperationalError, connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import SimpleTestCase

from cis.checks import MIGRATION_0056, mirror_logs_table_check
from cis.integrations.ethos import ethos_enabled
from cis.models.section import StudentRegistration


class MirrorLogsTableCheckTests(SimpleTestCase):

    def setUp(self):
        if not ethos_enabled():
            self.skipTest('needs the ethos app')
        self.table = StudentRegistration.mirror_logs.through._meta.db_table

    def _run(self, tables, applied=(MIGRATION_0056,), enabled=True):
        with mock.patch('cis.integrations.ethos.ethos_enabled', return_value=enabled), \
                mock.patch.object(MigrationRecorder, 'applied_migrations',
                                  return_value={key: None for key in applied}), \
                mock.patch.object(connection.introspection, 'table_names',
                                  **tables):
            return mirror_logs_table_check(None)

    def test_warns_with_the_fix_when_the_table_is_missing(self):
        messages = self._run({'return_value': ['cis_studentregistration']})
        self.assertEqual([m.id for m in messages], ['cis.W013'])
        self.assertIn(self.table, messages[0].msg)
        self.assertIn('editor.create_model(StudentRegistration.mirror_logs.through)',
                      messages[0].hint)

    def test_silent_when_the_table_exists(self):
        self.assertEqual(self._run({'return_value': [self.table]}), [])

    def test_silent_before_0056_has_run(self):
        self.assertEqual(self._run({'return_value': []}, applied=()), [])

    def test_silent_without_ethos(self):
        self.assertEqual(self._run({'return_value': []}, enabled=False), [])

    def test_silent_when_the_database_is_unreachable(self):
        self.assertEqual(self._run({'side_effect': OperationalError('down')}), [])
