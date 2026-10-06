"""Backfill HSAdministratorPosition.meta['manage_student_recommendation'] (#72).

The role form listed 'Yes' first with no initial, so a role whose meta never
had the key rendered as 'Yes' when staff opened the edit form, and an
unrelated save granted recommendation access. The form now defaults to 'No';
rows with the key missing, null or blank are set to 'No' here so the stored
value matches what staff see.

Rows that carry a value are normalised to the exact 'Yes'/'No' the form
offers: the access checks accept any casing (iexact), the form's choices do
not. Anything other than yes/no is left alone -- the access checks already
treat it as 'No' and there is no basis to rewrite it. Ported from westmoreland
0063.
"""
from django.db import migrations

FLAG = 'manage_student_recommendation'


def _normalised(meta):
    """Return the value this row should store, or None to leave it alone."""
    if not isinstance(meta, dict):
        return 'No'

    value = meta.get(FLAG)
    if value is None or str(value).strip() == '':
        return 'No'

    canonical = str(value).strip().lower()
    if canonical not in ('yes', 'no'):
        return None

    canonical = canonical.title()
    return canonical if canonical != value else None


def normalise_flags(apps, schema_editor):
    HSAdministratorPosition = apps.get_model('cis', 'HSAdministratorPosition')

    updated = []
    for record in HSAdministratorPosition.objects.all().iterator():
        value = _normalised(record.meta)
        if value is None:
            continue

        record.meta = dict(record.meta) if isinstance(record.meta, dict) else {}
        record.meta[FLAG] = value
        updated.append(record)

    if updated:
        HSAdministratorPosition.objects.bulk_update(updated, ['meta'], batch_size=500)


def noop(apps, schema_editor):
    """The rows backfilled here are indistinguishable from ones already 'No'."""


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0098_historicalcustomuser_drop_sensitive_fields'),
    ]

    operations = [
        migrations.RunPython(normalise_flags, noop),
    ]
