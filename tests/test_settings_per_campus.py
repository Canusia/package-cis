"""#129: every setting is per campus by default in multi-campus mode.

STRICT keys (prefixed / EXTRA_CAMPUS_SCOPED_KEYS) keep MC-05's rules. CAMPUS
keys (everything not allow-listed) read the campus row, else the shared row,
raise with no campus set, and copy-on-write when a campus saves. GLOBAL keys
are one shared row. Single-campus deployments are unchanged.
"""
import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.campus_context import NoCampusContext, campus_context
from cis.models.course import Campus
from cis.models.settings import (
    CAMPUS, GLOBAL, GLOBAL_SETTING_KEYS, STRICT, Setting, is_campus_scoped,
    setting_scope, shared_settings)

PREFIXED = f'{settings.CAMPUS_CODE_PREFIX}_cis_registrations'
OTHER = 'cis.settings.hs_uploads'
MENU = 'cis.settings.menu'


def _campus(name):
    return Campus.objects.create(
        name=f'{name}-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}')


class ScopeTests(TestCase):
    def test_prefixed_and_extra_keys_are_strict(self):
        self.assertEqual(setting_scope(PREFIXED), STRICT)
        self.assertEqual(setting_scope('cis.settings.sis_settings'), STRICT)

    def test_allow_listed_keys_are_global(self):
        for key in GLOBAL_SETTING_KEYS:
            self.assertEqual(setting_scope(key), GLOBAL, key)
            self.assertFalse(is_campus_scoped(key))

    def test_everything_else_is_campus(self):
        self.assertEqual(setting_scope(OTHER), CAMPUS)
        self.assertTrue(is_campus_scoped(OTHER))
        # PREFIX + __name__ without the underscore (importer/exporter settings).
        unprefixed = f'{settings.CAMPUS_CODE_PREFIX}cis.settings.student_exporter'
        self.assertEqual(setting_scope(unprefixed), CAMPUS)

    def test_empty_key_is_not_campus_scoped(self):
        self.assertFalse(is_campus_scoped(''))


class AssignSettingsCampusTests(TestCase):
    def test_moves_only_strict_rows(self):
        from io import StringIO
        from django.core.management import call_command
        c1 = _campus('C1')
        Setting.objects.create(key=PREFIXED, value={})
        Setting.objects.create(key=OTHER, value={})
        call_command('assign_settings_campus', campus=c1.code, stdout=StringIO())
        self.assertEqual(Setting.objects.get(key=PREFIXED).campus, c1)
        # CAMPUS rows stay shared: they are the other campuses' fallback.
        self.assertIsNone(Setting.objects.get(key=OTHER).campus)


@override_settings(MULTI_CAMPUS=True)
class FallbackReadTests(TestCase):
    def setUp(self):
        self.c1, self.c2 = _campus('C1'), _campus('C2')
        Setting.objects.create(key=OTHER, value={'v': 'shared'}, campus=None)

    def test_campus_without_a_row_reads_the_shared_row(self):
        with campus_context(self.c1):
            self.assertEqual(Setting.objects.get(key=OTHER).value, {'v': 'shared'})
            self.assertEqual(Setting.get_value(OTHER, 'v'), 'shared')

    def test_campus_row_wins(self):
        Setting.objects.create(key=OTHER, value={'v': 'c1'}, campus=self.c1)
        with campus_context(self.c1):
            self.assertEqual(Setting.objects.get(key=OTHER).value, {'v': 'c1'})
        with campus_context(self.c2):
            self.assertEqual(Setting.objects.get(key=OTHER).value, {'v': 'shared'})

    def test_exactly_one_row_through_every_accessor(self):
        Setting.objects.create(key=OTHER, value={'v': 'c1'}, campus=self.c1)
        with campus_context(self.c1):
            qs = Setting.objects.filter(key=OTHER)
            self.assertEqual(qs.count(), 1)
            self.assertEqual(list(qs.values_list('value', flat=True)), [{'v': 'c1'}])
            self.assertEqual(qs.first().value, {'v': 'c1'})
            self.assertTrue(qs.exists())

    def test_no_campus_raises(self):
        with self.assertRaises(NoCampusContext):
            Setting.objects.get(key=OTHER)
        with self.assertRaises(NoCampusContext):
            Setting.get_value(OTHER, 'v')

    def test_strict_key_still_never_falls_back(self):
        Setting.objects.create(key=PREFIXED, value={'a': 1}, campus=None)
        with campus_context(self.c1):
            with self.assertRaises(Setting.DoesNotExist):
                Setting.objects.get(key=PREFIXED)

    def test_global_key_reads_the_shared_row_with_or_without_a_campus(self):
        Setting.objects.create(key=MENU, value={'m': 1})
        self.assertEqual(Setting.objects.get(key=MENU).value, {'m': 1})
        with campus_context(self.c2):
            self.assertEqual(Setting.objects.get(key=MENU).value, {'m': 1})

    def test_fallback_instance_is_marked(self):
        with campus_context(self.c1):
            row = Setting.objects.get(key=OTHER)
        self.assertEqual(row._fallback_campus, self.c1)


class SingleCampusFallbackUnchangedTests(TestCase):
    def test_no_narrowing(self):
        _campus('A')
        Setting.objects.create(key=OTHER, value={'v': 1})
        row = Setting.objects.get(key=OTHER)
        self.assertIsNone(getattr(row, '_fallback_campus', None))


@override_settings(MULTI_CAMPUS=True)
class CopyOnWriteTests(TestCase):
    def setUp(self):
        self.c1, self.c2 = _campus('C1'), _campus('C2')
        self.shared = Setting.objects.create(key=OTHER, value={'v': 'shared'}, campus=None)

    def _shared_value(self):
        return Setting._base_manager.get(pk=self.shared.pk).value

    def test_saving_a_fallback_row_creates_the_campus_row(self):
        with campus_context(self.c1):
            row = Setting.objects.get(key=OTHER)
            row.value = {'v': 'c1'}
            row.save()
            self.assertEqual(Setting.objects.get(key=OTHER).value, {'v': 'c1'})
        self.assertEqual(row.campus, self.c1)
        self.assertNotEqual(row.pk, self.shared.pk)
        self.assertEqual(self._shared_value(), {'v': 'shared'})

    def test_two_campuses_each_get_their_own_row(self):
        for campus, value in ((self.c1, 'one'), (self.c2, 'two')):
            with campus_context(campus):
                row = Setting.objects.get(key=OTHER)
                row.value = {'v': value}
                row.save()
        with campus_context(self.c1):
            self.assertEqual(Setting.get_value(OTHER, 'v'), 'one')
        with campus_context(self.c2):
            self.assertEqual(Setting.get_value(OTHER, 'v'), 'two')
        self.assertEqual(self._shared_value(), {'v': 'shared'})

    def test_update_or_create_writes_the_campus_row(self):
        with campus_context(self.c1):
            Setting.objects.update_or_create(key=OTHER, defaults={'value': {'v': 'c1'}})
            self.assertEqual(Setting.get_value(OTHER, 'v'), 'c1')
        self.assertEqual(self._shared_value(), {'v': 'shared'})

    def test_get_or_create_returns_the_fallback_without_writing(self):
        with campus_context(self.c1):
            row, created = Setting.objects.get_or_create(key=OTHER)
        self.assertFalse(created)
        self.assertEqual(row.pk, self.shared.pk)
        self.assertEqual(Setting._base_manager.filter(key=OTHER).count(), 1)

    def test_queryset_update_and_delete_never_touch_the_shared_row(self):
        with campus_context(self.c1):
            self.assertEqual(Setting.objects.filter(key=OTHER).update(value={'v': 'x'}), 0)
            Setting.objects.filter(key=OTHER).delete()
        self.assertEqual(self._shared_value(), {'v': 'shared'})

    def test_queryset_update_changes_the_campus_row(self):
        Setting.objects.create(key=OTHER, value={'v': 'c1'}, campus=self.c1)
        with campus_context(self.c1):
            Setting.objects.filter(key=OTHER).update(value={'v': 'new'})
            self.assertEqual(Setting.get_value(OTHER, 'v'), 'new')
        self.assertEqual(self._shared_value(), {'v': 'shared'})

    def test_deleting_a_fallback_instance_keeps_the_shared_row(self):
        with campus_context(self.c1):
            Setting.objects.get(key=OTHER).delete()
        self.assertTrue(Setting._base_manager.filter(pk=self.shared.pk).exists())

    def test_new_row_for_a_campus_key_belongs_to_the_campus(self):
        Setting._base_manager.filter(key=OTHER).delete()
        with campus_context(self.c2):
            Setting(key=OTHER, value={}).save()
        self.assertEqual(Setting._base_manager.get(key=OTHER).campus, self.c2)

    def test_manager_has_no_bulk_delete(self):
        self.assertFalse(hasattr(Setting.objects, 'delete'))

    def test_iterator_rows_are_marked_for_copy_on_write(self):
        with campus_context(self.c1):
            row = next(Setting.objects.filter(key=OTHER).iterator())
            row.value = {'v': 'c1'}
            row.save()
        self.assertEqual(row.campus, self.c1)
        self.assertEqual(self._shared_value(), {'v': 'shared'})
        self.assertEqual(Setting._base_manager.filter(key=OTHER).count(), 2)


@override_settings(MULTI_CAMPUS=True)
class SharedSettingsTests(TestCase):
    def setUp(self):
        self.c1 = _campus('C1')

    def test_shared_settings_reads_and_writes_the_shared_row_without_a_campus(self):
        with shared_settings():
            Setting(key=OTHER, value={'v': 1}).save()
            self.assertEqual(Setting.objects.get(key=OTHER).value, {'v': 1})
        self.assertIsNone(Setting._base_manager.get(key=OTHER).campus)

    def test_shared_settings_does_not_open_strict_keys(self):
        with shared_settings():
            with self.assertRaises(NoCampusContext):
                Setting.objects.get(key=PREFIXED)

    def test_install_defaults_writes_the_shared_row_with_no_campus(self):
        Setting.install_defaults(OTHER, {'a': 1})
        self.assertEqual(Setting._base_manager.get(key=OTHER, campus=None).value, {'a': 1})

    def test_install_defaults_with_a_campus_set_still_writes_the_shared_row(self):
        with campus_context(self.c1):
            Setting.install_defaults(OTHER, {'a': 1})
        self.assertFalse(Setting._base_manager.filter(key=OTHER, campus=self.c1).exists())

    def test_install_defaults_adds_new_keys_to_campus_rows_without_overwriting(self):
        Setting.objects.create(key=OTHER, value={'a': 'shared'}, campus=None)
        Setting.objects.create(key=OTHER, value={'a': 'mine'}, campus=self.c1)
        Setting.install_defaults(OTHER, {'a': 'default', 'b': 'new'})
        own = Setting._base_manager.get(key=OTHER, campus=self.c1).value
        self.assertEqual(own, {'a': 'mine', 'b': 'new'})

    def test_strict_install_defaults_unchanged(self):
        with campus_context(self.c1):
            Setting.install_defaults(PREFIXED, {'a': 1})
        self.assertTrue(Setting._base_manager.filter(key=PREFIXED, campus=self.c1).exists())


@override_settings(MULTI_CAMPUS=True)
class ScopeStatusTests(TestCase):
    def test_statuses(self):
        from cis.models.settings import setting_scope_status
        c1 = _campus('C1')
        Setting.objects.create(key=OTHER, value={}, campus=None)
        with campus_context(c1):
            self.assertEqual(setting_scope_status(MENU), 'global')
            self.assertEqual(setting_scope_status(OTHER), 'shared')
            Setting.objects.create(key=OTHER, value={}, campus=c1)
            self.assertEqual(setting_scope_status(OTHER), 'own')
            self.assertEqual(setting_scope_status(PREFIXED), 'own')

    @override_settings(MULTI_CAMPUS=False)
    def test_single_campus_has_no_status(self):
        from cis.models.settings import setting_scope_status
        self.assertIsNone(setting_scope_status(OTHER))
