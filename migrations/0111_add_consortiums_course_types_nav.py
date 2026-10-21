"""
Data migration: add "Consortiums" and "Course Types" to the ce_menu's
"High Schools" nav-item (name="highschools"), right after "Admin. Roles"
(name="school_roles"), in the cis.settings.menu Setting row.

Forwards  -- no-ops when the Setting row is absent (fresh installs get the
            entries from menu.install()); idempotent on repeated runs; no-ops
            (without raising) if the "highschools" nav-item or its sub_menu
            is missing or malformed.
Backwards -- removes the entries by name.

Same shape as 0084_add_document_types_nav.
"""
import json

from django.db import migrations


SETTING_KEY = "cis.settings.menu"
ROLE_KEY = "ce_menu"
PARENT_NAV_NAME = "highschools"
AFTER_NAME = "school_roles"

_ENTRIES = [
    {"label": "Consortiums", "name": "consortiums", "url": "cis:consortiums"},
    {"label": "Course Types", "name": "course_types", "url": "cis:course_types"},
]
_ENTRY_NAMES = {entry["name"] for entry in _ENTRIES}


def _patch_menu(setting_value, *, remove=False):
    """Add/remove _ENTRIES in the PARENT_NAV_NAME nav-item's sub_menu.

    Returns the (possibly modified) value dict. Never raises on unexpected
    shapes; leaves setting_value unchanged instead.
    """
    if ROLE_KEY not in setting_value:
        return setting_value

    try:
        items = json.loads(setting_value[ROLE_KEY])
    except (TypeError, ValueError):
        return setting_value
    if not isinstance(items, list):
        return setting_value

    parent = next(
        (i for i in items
         if isinstance(i, dict) and i.get("name") == PARENT_NAV_NAME),
        None)
    if parent is None:
        return setting_value

    sub_menu = parent.get("sub_menu")
    if not isinstance(sub_menu, list):
        return setting_value

    def _name(s):
        return s.get("name") if isinstance(s, dict) else None

    if remove:
        parent["sub_menu"] = [s for s in sub_menu if _name(s) not in _ENTRY_NAMES]
    else:
        present = {_name(s) for s in sub_menu}
        missing = [dict(e) for e in _ENTRIES if e["name"] not in present]
        if not missing:
            return setting_value
        names = [_name(s) for s in sub_menu]
        insert_at = (names.index(AFTER_NAME) + 1
                     if AFTER_NAME in names else len(sub_menu))
        sub_menu[insert_at:insert_at] = missing

    setting_value[ROLE_KEY] = json.dumps(items)
    return setting_value


def _apply(apps, remove):
    Setting = apps.get_model("cis", "Setting")
    try:
        setting = Setting.objects.get(key=SETTING_KEY)
    except Setting.DoesNotExist:
        return
    setting.value = _patch_menu(dict(setting.value), remove=remove)
    setting.save()


def add_nav(apps, schema_editor):
    _apply(apps, remove=False)


def remove_nav(apps, schema_editor):
    _apply(apps, remove=True)


class Migration(migrations.Migration):

    dependencies = [
        ("cis", "0110_consortium_course_type"),
    ]

    operations = [
        migrations.RunPython(add_nav, remove_nav),
    ]
