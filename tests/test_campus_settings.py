"""MC-05 (#29): per-campus Setting rows.

Setting gains a nullable campus (null = global). Keys carrying
CAMPUS_CODE_PREFIX plus a short list of named settings are campus-scoped.
When MULTI_CAMPUS is on, a lookup of a campus-scoped key is narrowed to
current_campus() by the Setting queryset itself -- so the ~370 existing
`Setting.objects.get(key=...)` call sites need no change -- and it raises
without a campus rather than falling back to the global row. Saving a
campus-scoped row fills its campus the same way.

Single-campus mode is untouched: no campus filtering, existing rows keep
campus NULL, and nothing is migrated.
"""
import uuid
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from cis.campus_context import NoCampusContext, campus_context
from cis.models.course import Campus
from cis.models.settings import Setting, is_campus_scoped

PREFIXED = f'{settings.CAMPUS_CODE_PREFIX}_cis_registrations'


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


class ScopeTests(TestCase):
    def test_prefixed_and_named_keys_are_campus_scoped(self):
        self.assertTrue(is_campus_scoped(PREFIXED))
        self.assertTrue(is_campus_scoped('cis.settings.sis_settings'))
        self.assertTrue(is_campus_scoped('cis_future_sections'))

    def test_other_keys_are_global(self):
        self.assertFalse(is_campus_scoped('cis.settings.menu'))
        self.assertFalse(is_campus_scoped('two_step'))


class SingleCampusUnchangedTests(TestCase):
    def test_lookups_and_saves_ignore_campus(self):
        _campus('A')
        _campus('B')
        Setting.objects.create(key=PREFIXED, value={'active_term': 'x'})
        row = Setting.objects.get(key=PREFIXED)
        self.assertIsNone(row.campus)
        self.assertEqual(Setting.get_value(PREFIXED, 'active_term'), 'x')

    def test_one_row_per_key_as_today(self):
        Setting.objects.create(key='cis.settings.menu', value={})
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Setting.objects.create(key='cis.settings.menu', value={})


@override_settings(MULTI_CAMPUS=True)
class MultiCampusTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')
        self.c2 = _campus('C2')

    def test_each_campus_has_its_own_row(self):
        with campus_context(self.c1):
            Setting.objects.create(key=PREFIXED, value={'active_term': 'c1-term'})
        with campus_context(self.c2):
            Setting.objects.create(key=PREFIXED, value={'active_term': 'c2-term'})

        with campus_context(self.c1):
            self.assertEqual(Setting.objects.get(key=PREFIXED).value['active_term'], 'c1-term')
            self.assertEqual(Setting.get_value(PREFIXED, 'active_term'), 'c1-term')
        with campus_context(self.c2):
            self.assertEqual(Setting.objects.get(key=PREFIXED).campus, self.c2)

    def test_no_fallback_to_the_global_row(self):
        Setting.objects.create(key=PREFIXED, value={'active_term': 'global'}, campus=None)
        with campus_context(self.c1):
            with self.assertRaises(Setting.DoesNotExist):
                Setting.objects.get(key=PREFIXED)
            self.assertEqual(Setting.get_value(PREFIXED, 'active_term'), '')

    def test_campus_scoped_lookup_without_a_campus_raises(self):
        with self.assertRaises(NoCampusContext):
            Setting.objects.get(key=PREFIXED)
        with self.assertRaises(NoCampusContext):
            Setting.get_value(PREFIXED, 'active_term')

    def test_global_keys_are_shared(self):
        Setting.objects.create(key='cis.settings.menu', value={'m': 1})
        with campus_context(self.c1):
            self.assertEqual(Setting.objects.get(key='cis.settings.menu').value, {'m': 1})
        with campus_context(self.c2):
            self.assertEqual(Setting.objects.get(key='cis.settings.menu').value, {'m': 1})

    def test_install_defaults_seeds_per_campus(self):
        with campus_context(self.c1):
            Setting.install_defaults(PREFIXED, {'a': 1})
        with campus_context(self.c2):
            Setting.install_defaults(PREFIXED, {'a': 2})
        self.assertEqual(Setting.objects.filter(key=PREFIXED, campus=self.c1).get().value, {'a': 1})
        self.assertEqual(Setting.objects.filter(key=PREFIXED, campus=self.c2).get().value, {'a': 2})

    def test_explicit_campus_argument_wins(self):
        Setting.objects.create(key=PREFIXED, value={}, campus=self.c2)
        with campus_context(self.c1):
            self.assertTrue(Setting.objects.filter(key=PREFIXED, campus=self.c2).exists())

    def test_same_key_twice_on_one_campus_refused(self):
        Setting.objects.create(key=PREFIXED, value={}, campus=self.c1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Setting.objects.create(key=PREFIXED, value={}, campus=self.c1)


class AssignSettingsCampusCommandTests(TestCase):
    def test_moves_global_campus_scoped_rows_to_the_campus(self):
        c1 = _campus('C1')
        Setting.objects.create(key=PREFIXED, value={'x': 1})
        Setting.objects.create(key='cis.settings.menu', value={})
        out = StringIO()
        call_command('assign_settings_campus', campus=c1.code, stdout=out)
        self.assertEqual(Setting.objects.get(key=PREFIXED).campus, c1)
        self.assertIsNone(Setting.objects.get(key='cis.settings.menu').campus)
        self.assertIn('1', out.getvalue())

    def test_dry_run_changes_nothing(self):
        c1 = _campus('C1')
        Setting.objects.create(key=PREFIXED, value={'x': 1})
        call_command('assign_settings_campus', campus=c1.code, dry_run=True, stdout=StringIO())
        self.assertIsNone(Setting.objects.get(key=PREFIXED).campus)
