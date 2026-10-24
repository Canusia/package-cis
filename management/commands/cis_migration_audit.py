"""Compare a database's cis migration history with the package (#98).

For a tenant moving from an in-tree ``cis`` whose migrations drifted from the
package's (nnu, westmoreland, csn, weber, wvup). Read-only: it changes
nothing, and prints

- tenant-only migrations: rows in django_migrations for app 'cis' that the
  package does not have (they are deleted from django_migrations at cutover,
  once their schema is accounted for);
- package migrations not yet applied, each with a verdict from the live
  schema:
    present  -- every table/column it adds already exists: record it with
                ``migrate cis <name> --fake`` (only after checking the types);
    missing  -- nothing it adds exists yet: let ``migrate`` run it;
    partial  -- some of it exists: needs a hand-written bridge;
    review   -- it alters, removes, renames or runs code: read it first;
    no-op    -- choices / help text only: nothing in the database changes.

The runbook is docs/migration-bridge.md.
"""
from django.core.management.base import BaseCommand
from django.db import connection, migrations
from django.db.migrations.loader import MigrationLoader

APP = 'cis'


def _table_columns():
    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))
    columns = {}

    def cols(table):
        if table not in columns:
            if table in tables:
                with connection.cursor() as cursor:
                    columns[table] = {
                        c.name for c in
                        connection.introspection.get_table_description(cursor, table)}
            else:
                columns[table] = set()
        return columns[table]
    return tables, cols


def schema_verdict(migration, state, tables, cols):
    """'present' / 'missing' / 'partial' / 'review' / 'no-op' for one migration, judged
    against the live schema. ``state`` is the project state just before it."""
    found, absent = 0, 0
    for op in migration.operations:
        if isinstance(op, migrations.CreateModel):
            table = op.options.get('db_table') or f'{APP}_{op.name.lower()}'
            found, absent = (found + 1, absent) if table in tables else (found, absent + 1)
        elif isinstance(op, migrations.AddField):
            model = state.apps.get_model(APP, op.model_name)
            field = op.field.clone()
            field.set_attributes_from_name(op.name)
            if field.many_to_many:
                through = f'{model._meta.db_table}_{op.name}'
                present = through in tables
            else:
                present = field.column in cols(model._meta.db_table)
            found, absent = (found + 1, absent) if present else (found, absent + 1)
        elif isinstance(op, migrations.AlterField) and not _schema_change(op, state):
            continue  # choices / help_text only: no schema to check
        else:
            return 'review'
        state = state.clone()
        op.state_forwards(APP, state)
    if found and absent:
        return 'partial'
    if found:
        return 'present'
    return 'missing' if absent else 'no-op'


# Field attributes PostgreSQL never sees: an AlterField changing only these
# needs no schema check.
_NON_DB_KWARGS = {'choices', 'help_text', 'verbose_name', 'validators',
                  'blank', 'error_messages', 'editable', 'default'}


def _schema_change(op, state):
    """True unless an AlterField changes only non-database attributes."""
    try:
        old = state.models[APP, op.model_name.lower()].fields[op.name]
    except KeyError:
        return True
    old_path, old_args, old_kwargs = old.deconstruct()[1:]
    new_path, new_args, new_kwargs = op.field.deconstruct()[1:]
    if old_path != new_path or old_args != new_args:
        return True
    keys = set(old_kwargs) | set(new_kwargs)
    return any(old_kwargs.get(k) != new_kwargs.get(k)
               for k in keys - _NON_DB_KWARGS)


class Command(BaseCommand):
    help = "Read-only: compare this database's cis migrations with the package's (#98)."

    def handle(self, *args, **options):
        loader = MigrationLoader(connection)
        package = {name for app, name in loader.disk_migrations if app == APP}
        applied = {name for app, name in loader.applied_migrations if app == APP}

        tenant_only = sorted(applied - package)
        self.stdout.write(f'Tenant-only cis migrations recorded ({len(tenant_only)}):')
        for name in tenant_only:
            self.stdout.write(f'  {name}')

        tables, cols = _table_columns()
        pending = [key for key in loader.graph.leaf_nodes(APP)]
        plan = [key for key in loader.graph.forwards_plan(pending[0])
                if key[0] == APP and key[1] not in applied] if pending else []
        self.stdout.write(f'\nPackage cis migrations not applied ({len(plan)}):')
        for key in plan:
            migration = loader.graph.nodes[key]
            state = loader.project_state(key, at_end=False)
            verdict = schema_verdict(migration, state, tables, cols)
            self.stdout.write(f'  {verdict:8} {key[1]}')
