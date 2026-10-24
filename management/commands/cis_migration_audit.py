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
    review   -- anything else (it alters, removes or renames something, adds
                an index or constraint, changes unique_together, runs code):
                read it first;
    no-op    -- choices / help text only, or proxy / unmanaged models:
                nothing in the database changes.

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
    against the live schema. ``state`` is the project state just before it.

    Table and column names come from the models rendered *after* each operation,
    so ``db_table``, ``through`` and Django's 63-character truncation are honoured."""
    found, absent = 0, 0
    for op in migration.operations:
        if isinstance(op, migrations.CreateModel):
            check = not (op.options.get('proxy') or op.options.get('managed') is False)
        elif isinstance(op, migrations.AddField):
            check = True
        elif isinstance(op, migrations.AlterField) and not _schema_change(op, state):
            check = False  # choices / help_text only: no schema to check
        else:
            return 'review'
        state = state.clone()
        op.state_forwards(APP, state)
        if not check:
            continue
        model = state.apps.get_model(APP, op.model_name if isinstance(
            op, migrations.AddField) else op.name)
        if isinstance(op, migrations.CreateModel):
            present = model._meta.db_table in tables
        else:
            field = model._meta.get_field(op.name)
            if field.many_to_many:
                if not field.remote_field.through._meta.auto_created:
                    continue  # explicit through: its own CreateModel has the table
                present = field.m2m_db_table() in tables
            else:
                present = field.column in cols(model._meta.db_table)
        found, absent = (found + 1, absent) if present else (found, absent + 1)
    if found and absent:
        return 'partial'
    if found:
        return 'present'
    return 'missing' if absent else 'no-op'


def pending_plan(graph, applied):
    """Unapplied cis migrations in apply order, planned to every cis leaf, and the
    leaves themselves (more than one means the package needs a merge migration)."""
    leaves = graph.leaf_nodes(APP)
    plan, seen = [], set()
    for leaf in leaves:
        for key in graph.forwards_plan(leaf):
            if key[0] == APP and key[1] not in applied and key not in seen:
                seen.add(key)
                plan.append(key)
    return plan, leaves


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
        plan, leaves = pending_plan(loader.graph, applied)
        if len(leaves) > 1:
            self.stdout.write(self.style.WARNING(
                f'\nWarning: cis has {len(leaves)} leaf migrations '
                f'({", ".join(name for _, name in leaves)}); planning to all of them.'))
        self.stdout.write(f'\nPackage cis migrations not applied ({len(plan)}):')
        for key in plan:
            migration = loader.graph.nodes[key]
            state = loader.project_state(key, at_end=False)
            verdict = schema_verdict(migration, state, tables, cols)
            self.stdout.write(f'  {verdict:8} {key[1]}')
