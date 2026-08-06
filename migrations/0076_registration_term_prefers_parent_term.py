"""Point sections on a child term at that term's parent.

`0075` backfilled every null `registration_term` with the section's own `term`.
The rule since then is narrower: registration happens against the term that
*owns* the academic term, so a child term -- a session or sub-term -- registers
under its parent, and only a term with no parent registers under itself.

This corrects the rows `0075` set, and anything else already sitting on a child
term. Rows whose registration term is neither the term nor its parent were
chosen deliberately and are left alone.

`update()` cannot dereference a joined field (`F('term__parent_id')`), so this
walks the parent terms instead -- there are a handful per tenant, not a
per-section query.

Forward-only: which rows `0075` touched is not recoverable, and reversing would
restore the behaviour this replaces.
"""
from django.db import migrations
from django.db.models import F


def prefer_parent_term(apps, schema_editor):
    ClassSection = apps.get_model('cis', 'ClassSection')
    Term = apps.get_model('cis', 'Term')

    for term_id, parent_id in Term.objects.filter(
        parent__isnull=False
    ).values_list('id', 'parent_id'):
        ClassSection.objects.filter(
            term_id=term_id,
            registration_term_id=F('term_id'),
        ).update(registration_term_id=parent_id)


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0075_backfill_class_section_registration_term'),
    ]

    operations = [
        migrations.RunPython(
            prefer_parent_term,
            migrations.RunPython.noop,
        ),
    ]
