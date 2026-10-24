"""cis_migration_audit (#98): verdicts for package migrations a drifted
tenant has not recorded, judged from the live schema."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import connection, migrations, models
from django.db.migrations.graph import MigrationGraph
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase

from cis.management.commands.cis_migration_audit import pending_plan, schema_verdict

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


class SyntheticMigrationTests(TestCase):
    """Hand-built migrations on top of the package's latest state (#98 review)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        loader = MigrationLoader(connection)
        cls.state = loader.project_state(loader.graph.leaf_nodes('cis')[-1])

    def _verdict(self, operations, tables=(), columns=None):
        migration = migrations.Migration('9999_synthetic', 'cis')
        migration.operations = operations
        columns = columns or {}
        return schema_verdict(migration, self.state.clone(), set(tables),
                              lambda t: set(columns.get(t, ())))

    def _m2m(self, name, **kwargs):
        return migrations.AddField(
            model_name='classsection', name=name,
            field=models.ManyToManyField(blank=True, related_name='+', to='cis.term',
                                         **kwargs))

    def test_m2m_db_table_is_honoured(self):
        op = self._m2m('audit_terms', db_table='audit_custom_terms')
        self.assertEqual(self._verdict([op], tables={'audit_custom_terms'}), 'present')
        self.assertEqual(self._verdict([op], tables={'cis_classsection_audit_terms'}),
                         'missing')

    def test_long_m2m_table_name_is_truncated_like_django(self):
        name = 'audit_' + 'x' * 60
        op = self._m2m(name)
        self.assertGreater(len(f'cis_classsection_{name}'), 63)
        self.assertEqual(self._verdict([op], tables={f'cis_classsection_{name}'}),
                         'missing')
        state = self.state.clone()
        op.state_forwards('cis', state)
        truncated = state.apps.get_model('cis', 'classsection')._meta.get_field(
            name).m2m_db_table()
        self.assertLessEqual(len(truncated), 63)
        self.assertEqual(self._verdict([op], tables={truncated}), 'present')

    def test_m2m_with_explicit_through_is_judged_by_its_create_model(self):
        through = migrations.CreateModel(
            name='AuditSectionTerm',
            fields=[
                ('id', models.AutoField(primary_key=True)),
                ('section', models.ForeignKey(on_delete=models.CASCADE,
                                              to='cis.classsection')),
                ('term', models.ForeignKey(on_delete=models.CASCADE, to='cis.term')),
            ])
        op = self._m2m('audit_terms', through='cis.AuditSectionTerm')
        self.assertEqual(self._verdict([through, op], tables={'cis_auditsectionterm'}),
                         'present')
        self.assertEqual(self._verdict([through, op]), 'missing')

    def test_no_op_alter_field_advances_the_state(self):
        alter = migrations.AlterField(
            model_name='classsection', name='room',
            field=models.CharField(blank=True, max_length=50, help_text='audit'))
        add = migrations.AddField(model_name='classsection', name='audit_flag',
                                  field=models.BooleanField(default=False))
        with mock.patch.object(alter, 'state_forwards',
                               wraps=alter.state_forwards) as forwards:
            verdict = self._verdict([alter, add],
                                    columns={'cis_classsection': {'audit_flag'}})
        forwards.assert_called_once()
        self.assertEqual(verdict, 'present')

    def test_proxy_and_unmanaged_models_have_no_table(self):
        proxy = migrations.CreateModel(name='AuditTermProxy', fields=[],
                                       options={'proxy': True}, bases=('cis.term',))
        unmanaged = migrations.CreateModel(
            name='AuditView', fields=[('id', models.AutoField(primary_key=True))],
            options={'managed': False})
        self.assertEqual(self._verdict([proxy]), 'no-op')
        self.assertEqual(self._verdict([unmanaged]), 'no-op')

    def test_add_index_is_review(self):
        op = migrations.AddIndex(model_name='classsection',
                                 index=models.Index(fields=['id'], name='audit_idx'))
        self.assertEqual(self._verdict([op]), 'review')


class PendingPlanTests(TestCase):
    def test_plans_over_every_leaf_once(self):
        graph = MigrationGraph()
        for name in ('0001', '0002a', '0002b'):
            graph.add_node(('cis', name), None)
        graph.add_dependency(None, ('cis', '0002a'), ('cis', '0001'))
        graph.add_dependency(None, ('cis', '0002b'), ('cis', '0001'))
        plan, leaves = pending_plan(graph, applied=set())
        self.assertEqual(len(leaves), 2)
        self.assertEqual(plan[0], ('cis', '0001'))
        self.assertEqual(sorted(plan), [('cis', '0001'), ('cis', '0002a'), ('cis', '0002b')])

    def test_command_warns_on_several_leaves(self):
        out = StringIO()
        with mock.patch('cis.management.commands.cis_migration_audit.pending_plan',
                        return_value=([], [('cis', '0002a'), ('cis', '0002b')])):
            call_command('cis_migration_audit', stdout=out)
        self.assertIn('2 leaf migrations', out.getvalue())
