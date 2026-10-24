"""cis_migration_audit (#98): verdicts for package migrations a drifted
tenant has not recorded, judged from the live schema."""
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase

from cis.management.commands.cis_migration_audit import schema_verdict

DUE_DATES = ('registration_start_date', 'registration_end_date',
             'payment_due_date', 'grade_due_date')


class MigrationAuditTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.loader = MigrationLoader(connection)

    def _verdict(self, name, tables=(), columns=None):
        key = ('cis', name)
        migration = self.loader.graph.nodes[key]
        state = self.loader.project_state(key, at_end=False)
        columns = columns or {}
        return schema_verdict(
            migration, state, set(tables), lambda t: set(columns.get(t, ())))

    def test_columns_already_there_is_present(self):
        cols = {'cis_classsection': DUE_DATES, 'cis_historicalclasssection': DUE_DATES}
        self.assertEqual(self._verdict('0113_classsection_due_dates', columns=cols), 'present')

    def test_nothing_there_is_missing(self):
        self.assertEqual(self._verdict('0113_classsection_due_dates'), 'missing')

    def test_some_there_is_partial(self):
        cols = {'cis_classsection': DUE_DATES}
        self.assertEqual(self._verdict('0113_classsection_due_dates', columns=cols), 'partial')

    def test_choices_only_is_a_no_op(self):
        self.assertEqual(self._verdict('0115_pay_type_choices_callable'), 'no-op')

    def test_code_is_review(self):
        self.assertEqual(self._verdict('0101_hsadmin_permissions_backfill'), 'review')

    def test_command_runs_read_only(self):
        out = StringIO()
        call_command('cis_migration_audit', stdout=out)
        self.assertIn('Tenant-only cis migrations recorded', out.getvalue())
