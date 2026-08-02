"""
Data migration: inject the Course Certificates nav entry into the
cis.settings.menu Setting row for the instructor and highschool_admin portals.

The live sidebar is rendered from the cis.settings.menu Setting (draw_menu
reloads it from the DB), NOT from the hardcoded lists in cis/menu.py. Fresh
installs already get these entries from menu.install() defaults; this migration
brings existing tenants up to date.

Forwards  — no-ops when the Setting row is absent; idempotent on repeated runs.
Backwards — removes the injected entries by name.
"""
import json

from django.db import migrations


# Entry dicts kept identical to the menu.install() defaults so both code paths
# produce the same sidebar.
_INSTRUCTOR_ENTRY = {
    "type": "nav-item",
    "icon": "fas fa-fw fa-certificate",
    "name": "certificates",
    "label": "My Certificates",
    "url": "instructor:certificates",
}

_HS_ADMIN_ENTRY = {
    "type": "nav-item",
    "icon": "fas fa-fw fa-certificate",
    "name": "certificates",
    "label": "Course Certificates",
    "url": "highschool_admin:certificates",
}

# role key -> (entry dict, name string used for idempotency check)
_ROLE_ENTRIES = {
    "instructor_menu":       (_INSTRUCTOR_ENTRY, "certificates"),
    "highschool_admin_menu": (_HS_ADMIN_ENTRY,   "certificates"),
}

SETTING_KEY = "cis.settings.menu"


def _patch_menu(setting_value, role_key, entry, entry_name, *, remove=False):
    """Parse setting_value[role_key], add/remove the entry, store JSON back."""
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


def add_course_certificates_nav(apps, schema_editor):
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


def remove_course_certificates_nav(apps, schema_editor):
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
        ("cis", "0066_historicalhighschool_historicalstudentregistration"),
    ]

    operations = [
        migrations.RunPython(
            add_course_certificates_nav,
            remove_course_certificates_nav,
        ),
    ]
