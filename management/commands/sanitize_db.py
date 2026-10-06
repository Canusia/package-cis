"""
Randomize PII in a *copy* of a tenant database so it can be shared with developers.

The command rewrites rows in place, so it only runs when DEPLOY_TYPE is local/dev
and the configured database name ends with ``_sanitized``. Typical use:

    # 1. copy the working database
    createdb -U postgres <tenant>_sanitized
    pg_dump -U postgres -d <tenant> | psql -q -U postgres -d <tenant>_sanitized

    # 2. point Django at the copy and sanitize it (needs `pip install faker`)
    DATABASE_URL=postgres://postgres:postgres@<host>:5432/<tenant>_sanitized \\
        python manage.py sanitize_db

    # 3. dump the copy for sharing
    pg_dump -U postgres -d <tenant>_sanitized -Fc --no-owner --no-privileges \\
        -f <tenant>_sanitized.dump

What is rewritten is listed in ``cis.sanitize``; other packages and tenants add
targets with ``cis.sanitize.register_columns()`` / ``register_truncate()`` or the
``SANITIZE_DB_EXTRA`` setting. Every target whose table or column is missing is
skipped. Supersedes the per-tenant ``anonymize_users`` command.
"""
import json
import os
import random

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from cis import sanitize


def get_database_name():
    return connection.settings_dict.get('NAME', '')


class Command(BaseCommand):
    help = 'Randomize PII in a copy of the database (DB name must end with _sanitized).'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='MyceDev-2026!',
                            help='Password set on every account (default: MyceDev-2026!).')
        parser.add_argument('--keep-domain', action='append', dest='keep_domains',
                            help='Users with this email domain keep name/email (password is still '
                                 'reset). Repeatable. Default: @canusia.com.')
        parser.add_argument('--seed', type=int, default=20261005, help='Random seed.')

    def handle(self, *args, **options):
        # Guards first: nothing below runs, not even the Faker import, unless both pass.
        reason = sanitize.check_guards(getattr(settings, 'DEPLOY_TYPE', None), get_database_name())
        if reason:
            raise CommandError(reason)

        try:
            from faker import Faker
        except ImportError:
            raise CommandError('sanitize_db needs Faker, which is not a runtime dependency of '
                               'cis: pip install faker')

        Faker.seed(options['seed'])
        random.seed(options['seed'])
        self.fake = Faker('en_US')
        self.stats = {}
        self.password_hash = make_password(options['password'])
        self.keep_domains = tuple(d.lower() for d in (options['keep_domains']
                                                      or sanitize.DEFAULT_KEEP_DOMAINS))
        extra = getattr(settings, 'SANITIZE_DB_EXTRA', None) or {}
        try:
            columns = sanitize.column_targets(extra)
        except ValueError as exc:
            raise CommandError(str(exc))

        with transaction.atomic(), connection.cursor() as cur:
            self.cur = cur
            self.tables = set(connection.introspection.table_names(cur))
            self._descriptions = {}
            self.users()
            self.students()
            self.sync_allauth_emails()
            for table, col, kind in columns:
                self.apply(table, col, kind)
            # After the live rows (including cis_student.meta) are final.
            for table, live, cols in sanitize.HISTORY_SYNC:
                self.sync_history(table, live, cols)
            self.report_scheduler_data()
            self.truncate(sanitize.truncate_targets(extra))

        for key in sorted(self.stats):
            self.stdout.write(f'{key}: {self.stats[key]}')
        self.stdout.write(self.style.SUCCESS(
            f"Done. Every account's password is now {options['password']!r}."))

    # ------------------------------------------------------------ schema helpers
    def bump(self, key, n=1):
        self.stats[key] = self.stats.get(key, 0) + n

    def columns(self, table):
        """{column: FieldInfo} for an existing table, {} for a missing one."""
        if table not in self.tables:
            return {}
        if table not in self._descriptions:
            self._descriptions[table] = {
                f.name: f for f in connection.introspection.get_table_description(self.cur, table)}
        return self._descriptions[table]

    def pk(self, table):
        return connection.introspection.get_primary_key_column(self.cur, table) or 'id'

    def has(self, table, col):
        return col in self.columns(table)

    def fit(self, table, col, value):
        size = getattr(self.columns(table).get(col), 'internal_size', None)
        if isinstance(value, str) and isinstance(size, int) and 0 < size < len(value):
            return value[:size]
        return value

    def empty(self, table, col):
        info = self.columns(table).get(col)
        return None if info is None or info.null_ok else ''

    def unique_digits(self, n, digits=8):
        return [str(v) for v in random.sample(range(10 ** (digits - 1), 10 ** digits), n)]

    # ------------------------------------------------------------ generic kinds
    def apply(self, table, col, kind):
        if not self.has(table, col):
            self.bump('skipped_missing_targets')
            return
        fake = self.fake
        generators = {
            'lorem': lambda v: sanitize.lorem_like(v, fake),
            'name': lambda v: fake.name(),
            'first_name': lambda v: fake.first_name(),
            'last_name': lambda v: fake.last_name(),
            'email': lambda v: fake.email(),
            'phone': lambda v: sanitize.phone(fake),
            'street': lambda v: fake.street_address(),
            'city': lambda v: fake.city(),
            'zip': lambda v: fake.zipcode(),
            'upload': lambda v: f'redacted/{table}/{fake.uuid4()}{os.path.splitext(v)[1][:10]}',
        }
        if kind == 'signature':
            self.cur.execute(f"update {table} set {col} = %s where coalesce({col}::text, '') <> ''",
                             [sanitize.SIGNATURE_ON_FILE])
            self.bump(f'{table}.{col}', self.cur.rowcount)
        elif kind == 'blank':
            self.cur.execute(f"update {table} set {col} = %s where coalesce({col}::text, '') <> ''",
                             [self.empty(table, col)])
            self.bump(f'{table}.{col}', self.cur.rowcount)
        elif kind == 'unique_digits':
            pk = self.pk(table)
            self.cur.execute(f'select {pk} from {table}')
            ids = [r[0] for r in self.cur.fetchall()]
            self.cur.executemany(f'update {table} set {col} = %s where {pk} = %s',
                                 list(zip(self.unique_digits(len(ids)), ids)))
            self.bump(f'{table}.{col}', len(ids))
        elif kind in generators:
            self.update_text(table, col, generators[kind])
        elif kind == 'embedded_emails':
            self.update_text(table, col, lambda v: sanitize.replace_embedded_emails(v, self.keep_domains))
        elif kind == 'json':
            self.update_json(table, col, lambda d: sanitize.scrub_json(d, fake))
        elif kind == 'json_clear':
            self.update_json(table, col, lambda d: {})
        elif kind == 'embedded_emails_json':
            self.update_json(table, col, lambda d: sanitize.replace_embedded_emails(d, self.keep_domains))
        elif kind == 'json_secrets':
            # Values are never printed: only the count of blanked keys is reported.
            self.update_json(table, col, lambda d: sanitize.blank_secrets(d)[0])

    def update_text(self, table, col, fn):
        pk = self.pk(table)
        self.cur.execute(f"select {pk}, {col} from {table} where coalesce({col}::text, '') <> ''")
        for rid, val in self.cur.fetchall():
            new = self.fit(table, col, fn(val))
            if new != val:
                self.cur.execute(f'update {table} set {col} = %s where {pk} = %s', [new, rid])
                self.bump(f'{table}.{col}')

    def update_json(self, table, col, fn):
        pk = self.pk(table)
        self.cur.execute(f'select {pk}, {col} from {table} where {col} is not null')
        for rid, val in self.cur.fetchall():
            try:
                data = json.loads(val) if isinstance(val, str) else val
            except ValueError:
                continue
            new = fn(data)
            if new != data:
                self.cur.execute(f'update {table} set {col} = %s where {pk} = %s',
                                 [json.dumps(new), rid])
                self.bump(f'{table}.{col}')

    # ------------------------------------------------------------ dedicated steps
    def users(self):
        table = 'cis_customuser'
        fake_cols = [c for c in sanitize.CUSTOMUSER_FAKE_COLUMNS if self.has(table, c)]
        blank_cols = [c for c in sanitize.CUSTOMUSER_BLANK_COLUMNS if self.has(table, c)]
        self.cur.execute(f'select id, email{", date_of_birth" if "date_of_birth" in fake_cols else ""} '
                         f'from {table}')
        rows = self.cur.fetchall()
        psids = self.unique_digits(len(rows), digits=7)
        used = set()
        for row, psid in zip(rows, psids):
            uid, email = row[0], row[1]
            dob = row[2] if len(row) > 2 else None
            if email and email.lower().endswith(self.keep_domains):
                self.cur.execute(f'update {table} set password=%s where id=%s', [self.password_hash, uid])
                self.bump(f'{table}.kept_internal')
                continue
            first, last = self.fake.first_name(), self.fake.last_name()
            new_email = f'{first}.{last}.{uid}@example.com'.lower().replace("'", '')
            while new_email in used:
                new_email = f'{first}.{last}.{uid}.{random.randint(1, 999)}@example.com'.lower()
            used.add(new_email)
            values = {
                'first_name': first, 'last_name': last, 'username': new_email, 'email': new_email,
                'psid': psid, 'address1': self.fake.street_address(), 'city': self.fake.city(),
                'postal_code': self.fake.zipcode(), 'primary_phone': sanitize.phone(self.fake),
                'password': self.password_hash,
                # DOB keeps its year so ages and grade-level logic stay realistic.
                'date_of_birth': self.fake.date_between_dates(dob.replace(month=1, day=1),
                                                              dob.replace(month=12, day=28))
                if dob else None,
            }
            sets = {c: self.fit(table, c, values[c]) for c in fake_cols}
            sets.update({c: self.empty(table, c) for c in blank_cols})
            self.cur.execute(f'update {table} set {", ".join(f"{c}=%s" for c in sets)} where id=%s',
                             list(sets.values()) + [uid])
            self.bump(f'{table}.randomized')

    def students(self):
        table = 'cis_student'
        if table not in self.tables:
            return
        id_cols = [c for c in sanitize.STUDENT_ID_COLUMNS if self.has(table, c)]
        parent_cols = {c: k for c, k in sanitize.STUDENT_PARENT_COLUMNS.items() if self.has(table, c)}
        blank_cols = [c for c in sanitize.STUDENT_BLANK_COLUMNS if self.has(table, c)]
        self.cur.execute(f'select id from {table}')
        ids = [r[0] for r in self.cur.fetchall()]
        new_ids = {c: self.unique_digits(len(ids), digits=10 if c == 'state_id' else 8) for c in id_cols}
        for i, sid in enumerate(ids):
            first, last = self.fake.first_name(), self.fake.last_name()
            values = {'first_name': first, 'last_name': last,
                      'email': f'{first}.{last}.{i}@example.com'.lower().replace("'", ''),
                      'phone': sanitize.phone(self.fake)}
            sets = {c: new_ids[c][i] for c in id_cols}
            sets.update({c: self.fit(table, c, values[k]) for c, k in parent_cols.items()})
            sets.update({c: self.empty(table, c) for c in blank_cols})
            if sets:
                self.cur.execute(f'update {table} set {", ".join(f"{c}=%s" for c in sets)} where id=%s',
                                 list(sets.values()) + [sid])
            self.bump(f'{table}.randomized')

        # Shuffle demographics across students: keeps the distribution, breaks the link to a person.
        for col in sanitize.STUDENT_SHUFFLE_COLUMNS:
            if not self.has(table, col):
                continue
            self.cur.execute(f'select id, {col} from {table}')
            rows = self.cur.fetchall()
            values = [r[1] for r in rows]
            random.shuffle(values)
            self.cur.executemany(f'update {table} set {col}=%s where id=%s',
                                 [(v, r[0]) for v, r in zip(values, rows)])
            self.bump(f'{table}.shuffled_columns')

    def sync_allauth_emails(self):
        """allauth keeps its own copy of each user's address; point it at the new one."""
        if not self.has('account_emailaddress', 'email'):
            return
        self.cur.execute('update account_emailaddress a set email = u.email '
                         'from cis_customuser u where a.user_id = u.id and a.email <> u.email')
        self.bump('account_emailaddress.email', self.cur.rowcount)

    def sync_history(self, table, live, cols):
        """Copy sanitized columns onto simple_history rows; drop rows whose live row is gone."""
        cols = [c for c in cols if self.has(table, c) and self.has(live, c)]
        if not cols:
            return
        sets = ', '.join(f'{c} = l.{c}' for c in cols)
        self.cur.execute(f'update {table} h set {sets} from {live} l where h.id = l.id')
        self.bump(f'{table}.synced', self.cur.rowcount)
        self.cur.execute(f'delete from {table} h where not exists (select 1 from {live} l where l.id = h.id)')
        self.bump(f'{table}.orphans_deleted', self.cur.rowcount)

    def report_scheduler_data(self):
        if self.has('report_reportscheduler', 'data'):
            self.update_json('report_reportscheduler', 'data',
                             lambda d: {k: v for k, v in d.items() if k != 'csrfmiddlewaretoken'}
                             if isinstance(d, dict) else d)

    def truncate(self, tables):
        for table in tables:
            if table not in self.tables:
                continue
            self.cur.execute(
                "select distinct cl.relname from pg_constraint co "
                "join pg_class cl on co.conrelid = cl.oid "
                "where co.contype = 'f' and co.confrelid = %s::regclass and cl.relname <> %s",
                [table, table])
            for (referencing,) in self.cur.fetchall():
                # TRUNCATE ... CASCADE empties these too: make it visible.
                self.bump(f'truncated.cascade.{referencing}')
            self.cur.execute(f'select count(*) from {table}')
            n = self.cur.fetchone()[0]
            self.cur.execute(f'truncate table {table} cascade')
            self.bump(f'truncated.{table}', n)
