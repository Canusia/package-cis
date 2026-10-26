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
