"""
Data migration: inject Support Requests nav entries into the cis.settings.menu
Setting row for ce, student, instructor, and highschool_admin portals.

Forwards  — no-ops when the Setting row is absent (fresh installs get the
            entry from menu.install() defaults); idempotent on repeated runs.
Backwards — removes the injected entries by name.
"""
import json

from django.db import migrations


# --------------------------------------------------------------------------- #
# Support-ticket nav entries, keyed by the Setting value dict key             #
# --------------------------------------------------------------------------- #

_CE_ENTRY = {
    "type": "nav-item",
    "icon": "fas fa-fw fa-ticket-alt",
    "name": "support_reqs",
    "label": "Support Requests",
    "sub_menu": [
        {"label": "All Requests", "name": "all_requests", "url": "support_ticket:requests"},
        {"label": "Summary",      "name": "summary",      "url": "support_ticket:summary"},
        {"label": "Manage Types", "name": "types",        "url": "support_ticket:types"},
    ],
}

_STUDENT_ENTRY = {
    "type": "nav-item",
    "icon": "fas fa-fw fa-question-circle",
    "name": "support",
    "label": "Support Requests",
    "url": "student_support_ticket:requests",
}

_INSTRUCTOR_ENTRY = {
    "type": "nav-item",
    "icon": "fas fa-fw fa-question-circle",
    "name": "support",
    "label": "Support Requests",
    "url": "instructor_support_ticket:requests",
}

_HS_ADMIN_ENTRY = {
    "type": "nav-item",
    "icon": "fas fa-fw fa-question-circle",
    "name": "support",
    "label": "Support Requests",
    "url": "hs_admin_support_ticket:requests",
}

# role key -> (entry dict, name string used for idempotency check)
_ROLE_ENTRIES = {
    "ce_menu":                (_CE_ENTRY,         "support_reqs"),
    "student_menu":           (_STUDENT_ENTRY,    "support"),
    "instructor_menu":        (_INSTRUCTOR_ENTRY, "support"),
    "highschool_admin_menu":  (_HS_ADMIN_ENTRY,   "support"),
}

SETTING_KEY = "cis.settings.menu"


def _patch_menu(setting_value, role_key, entry, entry_name, *, remove=False):
    """
    Parse the JSON string stored at setting_value[role_key], add/remove the
    entry, and store the new JSON string back.  Returns the modified value dict.
    """
    if role_key not in setting_value:
        return setting_value

    raw = setting_value[role_key]
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return setting_value

    if not isinstance(items, list):
        return setting_value

    if remove:
        items = [i for i in items if i.get("name") != entry_name]
    else:
        # idempotency: only add when not already present
        if not any(i.get("name") == entry_name for i in items):
            items.append(entry)

    setting_value[role_key] = json.dumps(items)
    return setting_value


def add_support_ticket_nav(apps, schema_editor):
    Setting = apps.get_model("cis", "Setting")

    try:
        setting = Setting.objects.get(key=SETTING_KEY)
    except Setting.DoesNotExist:
        # fresh install — menu.install() will include the entries; nothing to do
        return

    value = dict(setting.value)  # shallow copy
    for role_key, (entry, name) in _ROLE_ENTRIES.items():
        value = _patch_menu(value, role_key, entry, name, remove=False)

    setting.value = value
    setting.save()


def remove_support_ticket_nav(apps, schema_editor):
    Setting = apps.get_model("cis", "Setting")

    try:
        setting = Setting.objects.get(key=SETTING_KEY)
    except Setting.DoesNotExist:
        return

    value = dict(setting.value)
    for role_key, (entry, name) in _ROLE_ENTRIES.items():
        value = _patch_menu(value, role_key, entry, name, remove=True)

    setting.value = value
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
        ("cis", "0063_bulkenrollbatch_bulkenrollrow"),
    ]

    operations = [
        migrations.RunPython(
            add_support_ticket_nav,
            remove_support_ticket_nav,
        ),
    ]
