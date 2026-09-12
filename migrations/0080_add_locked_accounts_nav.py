"""
Data migration: inject the "Locked Accounts" sub-menu entry into the
ce_menu's "Staff" nav-item (name="users") in the cis.settings.menu Setting
row.

Forwards  — no-ops when the Setting row is absent (fresh installs get the
            entry from menu.install() defaults); idempotent on repeated
            runs; no-ops (without raising) if the "users" nav-item is
            missing or its sub_menu is absent/malformed.
Backwards — removes the injected entry by name.
"""
import json

from django.db import migrations


SETTING_KEY = "cis.settings.menu"
ROLE_KEY = "ce_menu"
PARENT_NAV_NAME = "users"
ENTRY_NAME = "locked_users"

_ENTRY = {
    "label": "Locked Accounts",
    "name": ENTRY_NAME,
    "url": "cis:locked_users",
}


def _patch_menu(setting_value, *, remove=False):
    """
    Parse the JSON string stored at setting_value[ROLE_KEY], find the
    nav-item named PARENT_NAV_NAME, and add/remove ENTRY from its sub_menu.
    Returns the modified value dict. Defensive: never raises on unexpected
    shapes, just leaves setting_value unchanged in that case.
    """
    if ROLE_KEY not in setting_value:
        return setting_value

    raw = setting_value[ROLE_KEY]
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return setting_value

    if not isinstance(items, list):
        return setting_value

    parent = None
    for item in items:
        if isinstance(item, dict) and item.get("name") == PARENT_NAV_NAME:
            parent = item
            break

    if parent is None:
        # "users" nav-item missing (hand-edited menu) — nothing to patch.
        return setting_value

    sub_menu = parent.get("sub_menu")
    if not isinstance(sub_menu, list):
        if remove:
            # nothing to remove
            return setting_value
        # no sub_menu to insert into — leave menu untouched rather than
        # guessing at a shape.
        return setting_value

    if remove:
        parent["sub_menu"] = [s for s in sub_menu if not (isinstance(s, dict) and s.get("name") == ENTRY_NAME)]
    else:
        if not any(isinstance(s, dict) and s.get("name") == ENTRY_NAME for s in sub_menu):
            # Insert right after the first entry ("All Staff"), before
            # "Scheduled Tasks"; fall back to append if sub_menu is shorter
            # than expected.
            insert_at = 1 if len(sub_menu) >= 1 else 0
            sub_menu.insert(insert_at, dict(_ENTRY))
        parent["sub_menu"] = sub_menu

    setting_value[ROLE_KEY] = json.dumps(items)
    return setting_value


def add_locked_accounts_nav(apps, schema_editor):
    Setting = apps.get_model("cis", "Setting")

    try:
        setting = Setting.objects.get(key=SETTING_KEY)
    except Setting.DoesNotExist:
        # fresh install — menu.install() will include the entry; nothing to do
        return

    value = dict(setting.value)  # shallow copy
    value = _patch_menu(value, remove=False)

    setting.value = value
    setting.save()


def remove_locked_accounts_nav(apps, schema_editor):
    Setting = apps.get_model("cis", "Setting")

    try:
        setting = Setting.objects.get(key=SETTING_KEY)
    except Setting.DoesNotExist:
        return

    value = dict(setting.value)
    value = _patch_menu(value, remove=True)

    setting.value = value
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
        ("cis", "0079_coursedocumentrequirement"),
    ]

    operations = [
        migrations.RunPython(
            add_locked_accounts_nav,
            remove_locked_accounts_nav,
        ),
    ]
