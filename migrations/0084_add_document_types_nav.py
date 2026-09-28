"""
Data migration: add "Document Types" to the ce_menu's "Classes" nav-item
(name="classes"), right after "Subjects" (name="cohorts"), in the
cis.settings.menu Setting row (#45).

Forwards  -- no-ops when the Setting row is absent (fresh installs get the
            entry from menu.install()); idempotent on repeated runs; no-ops
            (without raising) if the "classes" nav-item or its sub_menu is
            missing or malformed.
Backwards -- removes the entry by name.

Same shape as 0080_add_locked_accounts_nav.
"""
import json

from django.db import migrations


SETTING_KEY = "cis.settings.menu"
ROLE_KEY = "ce_menu"
PARENT_NAV_NAME = "classes"
AFTER_NAME = "cohorts"
ENTRY_NAME = "document_types"

_ENTRY = {
    "label": "Document Types",
    "name": ENTRY_NAME,
    "url": "cis:document_types",
}


def _patch_menu(setting_value, *, remove=False):
    """Add/remove ENTRY in the PARENT_NAV_NAME nav-item's sub_menu.

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

    def _is_entry(s):
        return isinstance(s, dict) and s.get("name") == ENTRY_NAME

    if remove:
        parent["sub_menu"] = [s for s in sub_menu if not _is_entry(s)]
    elif not any(_is_entry(s) for s in sub_menu):
        names = [s.get("name") if isinstance(s, dict) else None for s in sub_menu]
        insert_at = (names.index(AFTER_NAME) + 1
                     if AFTER_NAME in names else len(sub_menu))
        sub_menu.insert(insert_at, dict(_ENTRY))
    else:
        return setting_value

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


def add_document_types_nav(apps, schema_editor):
    _apply(apps, remove=False)


def remove_document_types_nav(apps, schema_editor):
    _apply(apps, remove=True)


class Migration(migrations.Migration):

    dependencies = [
        ("cis", "0083_customuser_account_locked_at"),
    ]

    operations = [
        migrations.RunPython(
            add_document_types_nav,
            remove_document_types_nav,
        ),
    ]
