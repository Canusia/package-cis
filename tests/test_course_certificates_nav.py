"""
Tests for the Course Certificates sidebar nav entry.

Covers the data migration (0067_add_course_certificates_nav): forwards adds the
`certificates` entry to the instructor and highschool_admin menus, is
idempotent, no-ops when the Setting row is absent, and reverses cleanly.
"""
import json

from django.test import TestCase

from importlib import import_module

_migration = import_module("cis.migrations.0067_add_course_certificates_nav")
_add = _migration.add_course_certificates_nav
_remove = _migration.remove_course_certificates_nav
SETTING_KEY = _migration.SETTING_KEY


def _minimal_value():
    """A Setting.value dict with the two affected role keys, no cert entries."""
    return {
        "instructor_menu": json.dumps([
            {"type": "nav-item", "icon": "x", "name": "home",
             "label": "Home", "url": "instructor:dashboard"},
        ]),
        "highschool_admin_menu": json.dumps([
            {"type": "nav-item", "icon": "x", "name": "home",
             "label": "Home", "url": "highschool_admin:dashboard"},
        ]),
    }


class FakeApps:
    def get_model(self, app_label, model_name):
        from django.apps import apps
        return apps.get_model(app_label, model_name)


FAKE_APPS = FakeApps()


class CourseCertificatesNavMigrationTests(TestCase):

    def _seed_setting(self, value):
        from cis.models.settings import Setting
        obj, _ = Setting.objects.update_or_create(
            key=SETTING_KEY, defaults={"value": value})
        return obj

    def _items(self, role_key):
        from cis.models.settings import Setting
        setting = Setting.objects.get(key=SETTING_KEY)
        return json.loads(setting.value[role_key])

    def _names(self, items):
        return [i.get("name") for i in items]

    # Forwards ----------------------------------------------------------- #

    def test_forwards_adds_instructor_entry(self):
        self._seed_setting(_minimal_value())
        _add(FAKE_APPS, None)
        entry = next((i for i in self._items("instructor_menu")
                      if i.get("name") == "certificates"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["url"], "instructor:certificates")

    def test_forwards_adds_hs_admin_entry(self):
        self._seed_setting(_minimal_value())
        _add(FAKE_APPS, None)
        entry = next((i for i in self._items("highschool_admin_menu")
                      if i.get("name") == "certificates"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["url"], "highschool_admin:certificates")

    # Idempotency -------------------------------------------------------- #

    def test_forwards_idempotent_instructor(self):
        self._seed_setting(_minimal_value())
        _add(FAKE_APPS, None)
        _add(FAKE_APPS, None)
        self.assertEqual(
            self._names(self._items("instructor_menu")).count("certificates"), 1)

    def test_forwards_idempotent_hs_admin(self):
        self._seed_setting(_minimal_value())
        _add(FAKE_APPS, None)
        _add(FAKE_APPS, None)
        self.assertEqual(
            self._names(self._items("highschool_admin_menu")).count("certificates"), 1)

    # No-op / reverse ---------------------------------------------------- #

    def test_forwards_noop_when_no_setting_row(self):
        from cis.models.settings import Setting
        Setting.objects.filter(key=SETTING_KEY).delete()
        _add(FAKE_APPS, None)  # must not raise
        self.assertFalse(Setting.objects.filter(key=SETTING_KEY).exists())

    def test_reverse_removes_entries(self):
        self._seed_setting(_minimal_value())
        _add(FAKE_APPS, None)
        _remove(FAKE_APPS, None)
        self.assertNotIn("certificates", self._names(self._items("instructor_menu")))
        self.assertNotIn("certificates", self._names(self._items("highschool_admin_menu")))
