"""
Tests for the Support Requests sidebar nav entries.

Covers two surfaces:
  1. Data migration (0064_add_support_ticket_nav) forwards + reverse + idempotency.
  2. menu.install() defaults — fresh tenants get the entries from the defaults blob.
"""
import json

from django.test import TestCase, RequestFactory

from cis.menu import draw_menu, STUDENT_MENU, INSTRUCTOR_MENU, HS_ADMIN_MENU
from cis.settings.menu import menu as menu_setting

# Import the migration functions directly so we can unit-test them
# without going through the full migration executor.
from importlib import import_module

_migration = import_module("cis.migrations.0064_add_support_ticket_nav")
_add_support_ticket_nav = _migration.add_support_ticket_nav
_remove_support_ticket_nav = _migration.remove_support_ticket_nav
SETTING_KEY = _migration.SETTING_KEY


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _minimal_value():
    """A Setting.value dict with four role keys, none having support entries."""
    return {
        "ce_menu": json.dumps([
            {"type": "nav-item", "icon": "x", "name": "dashboard",
             "label": "Dashboard", "url": "cis:dashboard"},
        ]),
        "student_menu": json.dumps([
            {"type": "nav-item", "icon": "x", "name": "home",
             "label": "Home", "url": "student:dashboard"},
        ]),
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
    """Minimal apps registry that returns a real Model class by label."""
    def get_model(self, app_label, model_name):
        from django.apps import apps
        return apps.get_model(app_label, model_name)


FAKE_APPS = FakeApps()


# --------------------------------------------------------------------------- #
# Migration forwards / reverse / idempotency                                   #
# --------------------------------------------------------------------------- #

class SupportTicketNavMigrationTests(TestCase):

    def _seed_setting(self, value):
        from cis.models.settings import Setting
        obj, _ = Setting.objects.update_or_create(
            key=SETTING_KEY, defaults={"value": value}
        )
        return obj

    def _get_items(self, role_key):
        from cis.models.settings import Setting
        setting = Setting.objects.get(key=SETTING_KEY)
        return json.loads(setting.value[role_key])

    def _names(self, items):
        return [i.get("name") for i in items]

    # ------------------------------------------------------------------ #
    # Forwards                                                             #
    # ------------------------------------------------------------------ #

    def test_forwards_adds_ce_entry(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        names = self._names(self._get_items("ce_menu"))
        self.assertIn("support_reqs", names)

    def test_forwards_ce_entry_has_sub_menu(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        items = self._get_items("ce_menu")
        entry = next(i for i in items if i.get("name") == "support_reqs")
        sub_urls = [s["url"] for s in entry["sub_menu"]]
        self.assertIn("support_ticket:requests", sub_urls)
        self.assertIn("support_ticket:summary", sub_urls)
        self.assertIn("support_ticket:types", sub_urls)

    def test_forwards_adds_student_entry(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        items = self._get_items("student_menu")
        entry = next((i for i in items if i.get("name") == "support"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["url"], "student_support_ticket:requests")

    def test_forwards_adds_instructor_entry(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        items = self._get_items("instructor_menu")
        entry = next((i for i in items if i.get("name") == "support"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["url"], "instructor_support_ticket:requests")

    def test_forwards_adds_hs_admin_entry(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        items = self._get_items("highschool_admin_menu")
        entry = next((i for i in items if i.get("name") == "support"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["url"], "hs_admin_support_ticket:requests")

    # ------------------------------------------------------------------ #
    # Idempotency                                                          #
    # ------------------------------------------------------------------ #

    def test_forwards_idempotent_ce(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        _add_support_ticket_nav(FAKE_APPS, None)  # second run
        names = self._names(self._get_items("ce_menu"))
        self.assertEqual(names.count("support_reqs"), 1)

    def test_forwards_idempotent_student(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        _add_support_ticket_nav(FAKE_APPS, None)
        names = self._names(self._get_items("student_menu"))
        self.assertEqual(names.count("support"), 1)

    def test_forwards_idempotent_instructor(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        _add_support_ticket_nav(FAKE_APPS, None)
        names = self._names(self._get_items("instructor_menu"))
        self.assertEqual(names.count("support"), 1)

    def test_forwards_idempotent_hs_admin(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        _add_support_ticket_nav(FAKE_APPS, None)
        names = self._names(self._get_items("highschool_admin_menu"))
        self.assertEqual(names.count("support"), 1)

    # ------------------------------------------------------------------ #
    # No-op when Setting row is absent                                     #
    # ------------------------------------------------------------------ #

    def test_forwards_noop_when_no_setting_row(self):
        from cis.models.settings import Setting
        Setting.objects.filter(key=SETTING_KEY).delete()
        # Should not raise
        _add_support_ticket_nav(FAKE_APPS, None)
        self.assertFalse(Setting.objects.filter(key=SETTING_KEY).exists())

    # ------------------------------------------------------------------ #
    # Reverse                                                              #
    # ------------------------------------------------------------------ #

    def test_reverse_removes_ce_entry(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        _remove_support_ticket_nav(FAKE_APPS, None)
        names = self._names(self._get_items("ce_menu"))
        self.assertNotIn("support_reqs", names)

    def test_reverse_removes_student_entry(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        _remove_support_ticket_nav(FAKE_APPS, None)
        names = self._names(self._get_items("student_menu"))
        self.assertNotIn("support", names)

    def test_reverse_removes_instructor_entry(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        _remove_support_ticket_nav(FAKE_APPS, None)
        names = self._names(self._get_items("instructor_menu"))
        self.assertNotIn("support", names)

    def test_reverse_removes_hs_admin_entry(self):
        self._seed_setting(_minimal_value())
        _add_support_ticket_nav(FAKE_APPS, None)
        _remove_support_ticket_nav(FAKE_APPS, None)
        names = self._names(self._get_items("highschool_admin_menu"))
        self.assertNotIn("support", names)

    def test_reverse_noop_when_no_setting_row(self):
        from cis.models.settings import Setting
        Setting.objects.filter(key=SETTING_KEY).delete()
        _remove_support_ticket_nav(FAKE_APPS, None)
        self.assertFalse(Setting.objects.filter(key=SETTING_KEY).exists())


# --------------------------------------------------------------------------- #
# install() defaults — fresh-tenant coverage                                   #
# --------------------------------------------------------------------------- #

class SupportTicketNavInstallTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        request = RequestFactory().get("/")
        menu_setting(request=request).install()

    def _installed_items(self, role_key):
        from cis.settings.menu import menu as ms
        value = ms.from_db()
        return json.loads(value[role_key])

    def _names(self, items):
        return [i.get("name") for i in items]

    def test_install_ce_has_support_reqs(self):
        names = self._names(self._installed_items("ce_menu"))
        self.assertIn("support_reqs", names)

    def test_install_ce_sub_menu_urls(self):
        items = self._installed_items("ce_menu")
        entry = next(i for i in items if i.get("name") == "support_reqs")
        sub_urls = [s["url"] for s in entry["sub_menu"]]
        self.assertIn("support_ticket:requests", sub_urls)
        self.assertIn("support_ticket:summary", sub_urls)
        self.assertIn("support_ticket:types", sub_urls)

    def test_install_student_has_support(self):
        items = self._installed_items("student_menu")
        entry = next((i for i in items if i.get("name") == "support"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["url"], "student_support_ticket:requests")

    def test_install_instructor_has_support(self):
        items = self._installed_items("instructor_menu")
        entry = next((i for i in items if i.get("name") == "support"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["url"], "instructor_support_ticket:requests")

    def test_install_hs_admin_has_support(self):
        items = self._installed_items("highschool_admin_menu")
        entry = next((i for i in items if i.get("name") == "support"), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["url"], "hs_admin_support_ticket:requests")


# --------------------------------------------------------------------------- #
# draw_menu renders the support entry (integration smoke test)                 #
# --------------------------------------------------------------------------- #

class SupportTicketNavRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        request = RequestFactory().get("/")
        menu_setting(request=request).install()

    def test_student_menu_renders_support_link(self):
        html = draw_menu(STUDENT_MENU, "support", "", "student")
        self.assertIn("Support Requests", html)
        # URL resolves via student_support_ticket:requests
        self.assertIn("support_requests", html)

    def test_instructor_menu_renders_support_link(self):
        html = draw_menu(INSTRUCTOR_MENU, "support", "", "instructor")
        self.assertIn("Support Requests", html)
        # URL resolves via instructor_support_ticket:requests
        self.assertIn("support_requests", html)

    def test_hs_admin_menu_renders_support_link(self):
        html = draw_menu(HS_ADMIN_MENU, "support", "", "highschool_admin")
        self.assertIn("Support Requests", html)
        # URL resolves via hs_admin_support_ticket:requests
        self.assertIn("support_requests", html)
