"""Backfill ClassSection.registration_term from term.

The `default_registration_term` pre_save signal added alongside this migration
only fixes sections as they are saved. Sections already in the table stay null
until something happens to touch them, and every one of them keeps crashing the
class-apply charge with a NOT NULL violation on
`StudentTransaction.term_id` -- surfaced to the student as "You have already
added it" (ewu#53). SCCC saw ~1600 such sections; ewu had 1463, i.e. all of
them.

Forward-only: which rows were null is not information worth preserving, and
restoring them would restore the bug.
"""
from django.db import migrations
from django.db.models import F


def backfill_registration_term(apps, schema_editor):
    ClassSection = apps.get_model('cis', 'ClassSection')
    ClassSection.objects.filter(
        registration_term__isnull=True,
        term__isnull=False,
    ).update(registration_term=F('term'))


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0074_alter_historicalstudentregistration_status_and_more'),
    ]

    operations = [
        migrations.RunPython(
            backfill_registration_term,
            migrations.RunPython.noop,
        ),
    ]
