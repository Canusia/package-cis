"""Handing the instructor/faculty portal text to the portal packages (#81, #82).

cis stops registering its 'faculty_portal' / 'instructor_portal' settings when
the package's own setting is importable, deprecates the modules, reads the text
through cis.portal_text, and migration 0108 removes the leftover SettingRecord
rows. Patching find_spec / _has_module stands in for a tenant with or without
the packages.
"""
import importlib
import importlib.util
import sys
import warnings
from unittest import mock

from django.apps import apps as django_apps
from django.test import SimpleTestCase, TestCase

from cis import apps as cis_apps
from cis import portal_text as pt
from cis.models.settings import Setting

PORTAL_NAMES = ('faculty_portal', 'instructor_portal')


def _find_spec_without(*missing):
    real = importlib.util.find_spec

    def find_spec(name, *args, **kwargs):
        if any(name == m or name.startswith(m + '.') for m in missing):
            return None
        return real(name, *args, **kwargs)
    return find_spec


class OwnershipTests(SimpleTestCase):
    def test_owned_when_a_package_module_is_importable(self):
        for name in PORTAL_NAMES:
            with mock.patch.object(importlib.util, 'find_spec', return_value=object()):
                self.assertTrue(cis_apps.portal_text_owned_by_package(name))

    def test_not_owned_without_the_package(self):
        with mock.patch.object(importlib.util, 'find_spec',
                               side_effect=_find_spec_without('faculty', 'instructor')):
            for name in PORTAL_NAMES:
                self.assertFalse(cis_apps.portal_text_owned_by_package(name))

    def test_missing_parent_package_is_not_an_error(self):
        with mock.patch.object(importlib.util, 'find_spec', side_effect=ModuleNotFoundError):
            self.assertFalse(cis_apps.portal_text_owned_by_package('faculty_portal'))

    def test_other_settings_are_never_owned(self):
        self.assertFalse(cis_apps.portal_text_owned_by_package('student_portal'))

    def test_configurators_follow_ownership(self):
        names = {record['name'] for record in cis_apps.CisConfig.CONFIGURATORS}
        for name in PORTAL_NAMES:
            self.assertEqual(name in names, not cis_apps.portal_text_owned_by_package(name), name)
        self.assertIn('student_portal', names)


class DeprecationTests(SimpleTestCase):
    def test_importing_the_cis_modules_warns(self):
        for name in PORTAL_NAMES:
            module_name = f'cis.settings.{name}'
            saved = sys.modules.pop(module_name, None)
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    importlib.import_module(module_name)
                self.assertTrue(
                    any(issubclass(w.category, DeprecationWarning) and name in str(w.message)
                        for w in caught), name)
            finally:
                if saved is not None:
                    sys.modules[module_name] = saved


class PortalTextTests(TestCase):
    def _only(self, *present):
        sources = {m for modules in cis_apps.PORTAL_TEXT_OWNERS.values() for m in modules}
        real = pt._has_module
        return mock.patch.object(
            pt, '_has_module',
            side_effect=lambda name: name in present if name in sources else real(name))

    def setUp(self):
        Setting.objects.update_or_create(
            key='cis.settings.instructor_portal', defaults={'value': {'class_blurb': 'inst'}})
        Setting.objects.update_or_create(
            key='cis.settings.faculty_portal',
            defaults={'value': {'classes_blurb': 'fac old', 'x_blurb': 'fac x'}})
        Setting.objects.update_or_create(
            key='faculty.settings.faculty_portal', defaults={'value': {'classes_blurb': 'fac new'}})

    def test_cis_copy_without_the_packages_and_no_warning_leaks(self):
        with self._only(), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            sys.modules.pop('cis.settings.faculty_portal', None)
            self.assertEqual(pt.portal_text('instructor_portal')['class_blurb'], 'inst')
            self.assertEqual(pt.portal_text('faculty_portal')['classes_blurb'], 'fac old')
        self.assertFalse([w for w in caught if issubclass(w.category, DeprecationWarning)])

    def test_package_copy_when_installed(self):
        present = [m for m in cis_apps.PORTAL_TEXT_OWNERS['faculty_portal'] if pt._has_module(m)]
        if not present:
            self.skipTest('faculty package not installed')
        text = pt.portal_text('faculty_portal')
        self.assertEqual((text['classes_blurb'], text['x_blurb']), ('fac new', 'fac x'))

    def test_instructor_package_reads_the_same_row(self):
        present = [m for m in cis_apps.PORTAL_TEXT_OWNERS['instructor_portal'] if pt._has_module(m)]
        if not present:
            self.skipTest('instructor package not installed')
        self.assertEqual(pt.portal_text('instructor_portal')['class_blurb'], 'inst')

    def test_empty_when_the_row_is_missing(self):
        Setting.objects.filter(key='cis.settings.instructor_portal').delete()
        with self._only():
            self.assertEqual(pt.portal_text('instructor_portal'), {})


class HideMigrationTests(TestCase):
    def setUp(self):
        self.SettingRecord = django_apps.get_model('setting', 'SettingRecord')
        self.hide = importlib.import_module(
            'cis.migrations.0108_hide_packaged_portal_settings').hide

    def _record(self, name, app, categories=''):
        return self.SettingRecord.objects.create(
            name=name, app=app, title=name, categories=categories)

    def _names(self):
        return set(self.SettingRecord.objects.filter(
            name__in=PORTAL_NAMES + ('student_portal',)).values_list('app', 'name'))

    def test_removes_only_cis_rows_cis_no_longer_registers(self):
        self.SettingRecord.objects.filter(name__in=PORTAL_NAMES + ('student_portal',)).delete()
        for name in PORTAL_NAMES + ('student_portal',):
            self._record(name, 'cis')
        # (name, categories) is unique; a real install never has both rows,
        # since register_settings skips a name that already exists.
        self._record('instructor_portal', 'instructor', categories='4')
        configurators = [{'name': 'student_portal'}, {'name': 'instructor_portal'}]
        with mock.patch.object(cis_apps.CisConfig, 'CONFIGURATORS', configurators):
            self.hide(django_apps, None)
        self.assertEqual(self._names(), {
            ('cis', 'student_portal'), ('cis', 'instructor_portal'),
            ('instructor', 'instructor_portal')})

    def test_noop_while_cis_registers_both(self):
        self.SettingRecord.objects.filter(name__in=PORTAL_NAMES).delete()
        for name in PORTAL_NAMES:
            self._record(name, 'cis')
        configurators = [{'name': name} for name in PORTAL_NAMES]
        with mock.patch.object(cis_apps.CisConfig, 'CONFIGURATORS', configurators):
            self.hide(django_apps, None)
        self.assertEqual(
            self.SettingRecord.objects.filter(app='cis', name__in=PORTAL_NAMES).count(), 2)
